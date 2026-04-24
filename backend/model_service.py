import logging
import os
import shutil
import sys
import tempfile
import time
from typing import Any

import numpy as np

try:
    import psutil as psutil
except Exception:
    psutil = None  # type: ignore[assignment]

from backend.neuralset_mps_patch import apply_huggingface_text_mps_dtype_patch
from backend.runtime import RuntimeProfile, _profile_for_device, detect_runtime_profile

logger = logging.getLogger("braindiff.model_service")

_GIB = 1024 ** 3


def _resolve_text_backend_strategy(profile: RuntimeProfile) -> str:
    """Resolve the text-encoder placement strategy.

    Priority order:
    1. Explicit BRAIN_DIFF_TEXT_BACKEND env (auto | cpu | mps_split | mps_full_fp32)
    2. Auto:
       - non-MPS profile -> cpu
       - MPS profile -> mps_split on >=16 GiB RAM, else cpu

    Returns one of: "cpu" | "mps_split" | "mps_full_fp32"
    """
    explicit = os.environ.get("BRAIN_DIFF_TEXT_BACKEND", "").strip().lower()
    if explicit in ("cpu", "mps_split", "mps_full_fp32"):
        return explicit
    if explicit and explicit != "auto":
        logger.warning(
            "model_service: unknown BRAIN_DIFF_TEXT_BACKEND=%r; using auto",
            explicit,
        )

    if profile.device != "mps":
        return "cpu"
    total_ram = int(psutil.virtual_memory().total) if psutil is not None else 0
    if total_ram >= 16 * _GIB:
        return "mps_split"
    return "cpu"


def _apply_text_backend_strategy(strategy: str) -> None:
    """Set compatibility env flags so neuralset_mps_patch reads them correctly."""
    if strategy == "cpu":
        os.environ["BRAIN_DIFF_LLAMA_ON_CPU"] = "1"
        os.environ["BRAIN_DIFF_MPS_LLAMA_FP32_FULL"] = "0"
    elif strategy == "mps_split":
        os.environ["BRAIN_DIFF_LLAMA_ON_CPU"] = "0"
        os.environ["BRAIN_DIFF_MPS_LLAMA_FP32_FULL"] = "0"
        if "BRAIN_DIFF_MPS_TEXT_MAX_MEMORY" not in os.environ:
            total_ram = psutil.virtual_memory().total if psutil is not None else 0
            cap = "3500MiB" if total_ram >= 16 * _GIB else "2500MiB"
            os.environ["BRAIN_DIFF_MPS_TEXT_MAX_MEMORY"] = cap
    elif strategy == "mps_full_fp32":
        os.environ["BRAIN_DIFF_LLAMA_ON_CPU"] = "0"
        os.environ["BRAIN_DIFF_MPS_LLAMA_FP32_FULL"] = "1"


def _configure_whisper_defaults(profile: RuntimeProfile) -> None:
    """Set honest WhisperX defaults for each load attempt.

    CTranslate2/WhisperX has no MPS backend, so non-CUDA runs always use CPU.
    Only overrides vars that have not been set by the user.
    """
    if profile.device == "cuda":
        # faster-whisper on CUDA uses float16; CPU/MPS hosts must use int8 (float16 is unsupported on CPU).
        os.environ.setdefault("TRIBEV2_WHISPERX_COMPUTE_TYPE", "float16")
        return
    os.environ.setdefault("TRIBEV2_WHISPERX_DEVICE", "cpu")
    os.environ.setdefault("TRIBEV2_WHISPERX_MODEL", "tiny.en")
    os.environ.setdefault("TRIBEV2_WHISPERX_BATCH_SIZE", "4")
    os.environ.setdefault("TRIBEV2_WHISPERX_ALIGN_MODEL", "WAV2VEC2_ASR_LARGE_LV60K_960H")
    os.environ.setdefault("TRIBEV2_WHISPERX_COMPUTE_TYPE", "int8")


class TribeService:
    def __init__(self, model_revision: str = "facebook/tribev2", cache_folder: str = "./cache") -> None:
        self.model_revision = model_revision
        self.cache_folder = cache_folder
        self.model = None
        self.runtime_profile: RuntimeProfile | None = None
        self.text_backend_strategy: str | None = None

    def load(self) -> None:
        logger.info("TribeService.load:start model_revision=%s", self.model_revision)
        self._ensure_uvx_on_path()
        self._ensure_ffmpeg_on_path()
        try:
            try:
                from tribev2 import TribeModel  # type: ignore
            except ImportError:
                from tribev2.demo_utils import TribeModel  # type: ignore
        except Exception as err:
            raise RuntimeError("Failed to import TRIBEv2. Install facebookresearch/tribev2 first.") from err

        self._patch_tribev2_force_english()
        apply_huggingface_text_mps_dtype_patch()

        requested = detect_runtime_profile()
        last_err: Exception | None = None
        for device in requested.fallback_chain:
            profile = requested if device == requested.device else _profile_for_device(device)
            strategy = _resolve_text_backend_strategy(profile)
            _apply_text_backend_strategy(strategy)
            _configure_whisper_defaults(profile)

            whisper_device = os.environ.get("TRIBEV2_WHISPERX_DEVICE", "cuda" if profile.device == "cuda" else "cpu")
            whisper_model = os.environ.get("TRIBEV2_WHISPERX_MODEL", "—")
            whisper_batch = os.environ.get("TRIBEV2_WHISPERX_BATCH_SIZE", "—")
            mps_cap = os.environ.get("BRAIN_DIFF_MPS_TEXT_MAX_MEMORY", "—") if strategy == "mps_split" else "n/a"

            logger.info(
                "TribeService.load:attempt device=%s backend=%s text_strategy=%s "
                "whisper_device=%s whisper_model=%s whisper_batch=%s mps_cap=%s",
                profile.device,
                profile.backend,
                strategy,
                whisper_device,
                whisper_model,
                whisper_batch,
                mps_cap,
            )
            try:
                self.model = TribeModel.from_pretrained(
                    self.model_revision,
                    cache_folder=self.cache_folder,
                    device=profile.device,
                    config_update=profile.config_update,
                )
                self.runtime_profile = profile
                self.text_backend_strategy = strategy
                logger.info(
                    "TribeService.load:ok device=%s backend=%s text_strategy=%s",
                    profile.device,
                    profile.backend,
                    strategy,
                )
                return
            except Exception as err:
                last_err = err
                logger.warning(
                    "TribeService.load:attempt_failed device=%s err=%s",
                    profile.device,
                    err,
                    exc_info=True,
                )
        raise RuntimeError(f"Failed to load model {self.model_revision}: {last_err}") from last_err

    @staticmethod
    def _patch_tribev2_force_english() -> None:
        """Force TRIBEv2's text→speech step to always use English.

        Upstream TRIBEv2 calls ``langdetect.detect(text)`` and passes the result to
        ``gTTS(..., lang=...)``. On short or ambiguous inputs langdetect returns
        codes that gTTS does not support (e.g. ``'so'``, ``'cy'``), which aborts
        the whole diff job. BrainDiff is English-only by product decision, so we
        simply replace ``langdetect.detect`` with a constant. TRIBEv2 re-imports
        it inside ``get_events`` on every call, so the patch is picked up without
        touching upstream code. Non-English inputs are blocked at the UI layer.
        """
        try:
            import langdetect  # type: ignore
        except Exception as err:
            logger.warning("TribeService:patch_force_english:skipped (langdetect import failed: %s)", err)
            return
        langdetect.detect = lambda _text: "en"  # type: ignore[assignment]
        logger.info("TribeService:patch_force_english:applied (langdetect.detect → 'en')")

    @staticmethod
    def _ensure_uvx_on_path() -> None:
        if shutil.which("uvx"):
            return
        py_bin = os.path.dirname(sys.executable)
        uvx_candidate = os.path.join(py_bin, "uvx")
        if os.path.exists(uvx_candidate):
            os.environ["PATH"] = f"{py_bin}:{os.environ.get('PATH', '')}"

    @staticmethod
    def _ensure_ffmpeg_on_path() -> None:
        try:
            import imageio_ffmpeg  # type: ignore
        except Exception:
            logger.warning("imageio_ffmpeg not available; system ffmpeg must be installed")
            return
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = os.path.dirname(ffmpeg_exe)
        os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_exe
        # WhisperX shells out to literal `ffmpeg`. imageio_ffmpeg often ships a
        # versioned binary name (e.g. ffmpeg-macos-aarch64-v7.1), so ensure an
        # alias named `ffmpeg` exists on PATH.
        shim_dir = os.path.join(tempfile.gettempdir(), "braindiff-ffmpeg-shim")
        os.makedirs(shim_dir, exist_ok=True)
        shim_path = os.path.join(shim_dir, "ffmpeg")
        if not os.path.exists(shim_path):
            try:
                os.symlink(ffmpeg_exe, shim_path)
            except FileExistsError:
                pass
            except OSError:
                # If symlink is blocked, fall back to direct executable path.
                shim_path = ffmpeg_exe

        path_entries = [shim_dir, ffmpeg_dir, os.environ.get("PATH", "")]
        os.environ["PATH"] = ":".join([p for p in path_entries if p])

    def text_to_predictions(self, text: str) -> tuple[np.ndarray, Any, dict[str, int]]:
        if self.model is None:
            raise RuntimeError("TRIBEv2 model not loaded")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as handle:
            handle.write(text)
            temp_path = handle.name
        try:
            t0 = time.perf_counter()
            events = self.model.get_events_dataframe(text_path=temp_path)
            events_ms = int((time.perf_counter() - t0) * 1000)
            t1 = time.perf_counter()
            preds, segments = self.model.predict(events=events)
            predict_ms = int((time.perf_counter() - t1) * 1000)
            if hasattr(preds, "detach"):
                preds = preds.detach().cpu().numpy()
            elif hasattr(preds, "values"):
                preds = preds.values
            preds_np = np.array(preds, dtype=np.float32)
            if preds_np.ndim != 2:
                raise ValueError(f"Unexpected predictions shape: {preds_np.shape}")
            return preds_np, segments, {"events_ms": events_ms, "predict_ms": predict_ms}
        except Exception as err:
            msg = str(err)
            low = msg.lower()
            cause = str(err.__cause__) if err.__cause__ is not None else ""
            cause_low = cause.lower()
            blob = f"{low} {cause_low}"
            if "gated repo" in msg or "meta-llama/Llama-3.2-3B" in msg or "401 Client Error" in msg:
                raise RuntimeError(
                    "HF_AUTH_REQUIRED: Access to meta-llama/Llama-3.2-3B is required. Run `huggingface-cli login` with an approved token."
                ) from err
            if "whisperx failed" in low or "unsupported device" in blob or "ctranslate2" in blob:
                raise RuntimeError(
                    "WHISPERX_FAILED: Text transcription (WhisperX) failed. "
                    "On Apple Silicon, Whisper runs on CPU only; TRIBEv2 still uses the GPU. "
                    f"Detail: {msg}"
                ) from err
            if (
                "ffmpeg" in low
                and not ("whisperx failed" in low)
                and (
                    "not found" in low
                    or "missing" in low
                    or "no such file" in low
                    or "could not find" in low
                )
            ):
                raise RuntimeError("FFMPEG_REQUIRED: ffmpeg is required for text->speech transcription path.") from err
            if "'uvx'" in msg or "no such file or directory: 'uvx'" in low:
                raise RuntimeError("UVX_REQUIRED: uv/uvx is required for text->speech transcription path.") from err
            if "model loading went wrong" in low and err.__cause__ is not None:
                raise RuntimeError(f"LLAMA_LOAD_FAILED: {err.__cause__}") from err
            raise
        finally:
            os.unlink(temp_path)

    def audio_to_predictions(self, audio_path: str) -> tuple[np.ndarray, Any, dict[str, int]]:
        return self._media_to_predictions(audio_path, kind="audio")

    def video_to_predictions(self, video_path: str) -> tuple[np.ndarray, Any, dict[str, int]]:
        return self._media_to_predictions(video_path, kind="video")

    def _media_to_predictions(self, path: str, *, kind: str) -> tuple[np.ndarray, Any, dict[str, int]]:
        if self.model is None:
            raise RuntimeError("TRIBEv2 model not loaded")
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        kwargs = {"audio_path": path} if kind == "audio" else {"video_path": path}
        t0 = time.perf_counter()
        try:
            events = self.model.get_events_dataframe(**kwargs)
        except Exception as err:
            msg = str(err).lower()
            if "whisperx failed" in msg or "ctranslate2" in msg:
                raise RuntimeError(
                    f"WHISPERX_FAILED: Transcription step in the {kind} pipeline failed. Detail: {err}"
                ) from err
            raise
        events_ms = int((time.perf_counter() - t0) * 1000)
        t1 = time.perf_counter()
        preds, segments = self.model.predict(events=events)
        predict_ms = int((time.perf_counter() - t1) * 1000)
        if hasattr(preds, "detach"):
            preds = preds.detach().cpu().numpy()
        elif hasattr(preds, "values"):
            preds = preds.values
        preds_np = np.array(preds, dtype=np.float32)
        if preds_np.ndim != 2:
            raise ValueError(f"Unexpected predictions shape: {preds_np.shape}")
        return preds_np, segments, {"events_ms": events_ms, "predict_ms": predict_ms}
