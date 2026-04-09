import logging
import os
import platform
import shutil
import sys
import tempfile
import time
from typing import Any

import numpy as np

from backend.neuralset_mps_patch import apply_huggingface_text_mps_dtype_patch
from backend.runtime import RuntimeProfile, _profile_for_device, detect_runtime_profile

logger = logging.getLogger("braindiff.model_service")


class TribeService:
    def __init__(self, model_revision: str = "facebook/tribev2", cache_folder: str = "./cache") -> None:
        self.model_revision = model_revision
        self.cache_folder = cache_folder
        self.model = None
        self.runtime_profile: RuntimeProfile | None = None

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

        # Llama on CPU avoids MPS matmul/OOM/buffer limits on many M1/M2 configs; brain + audio still use MPS.
        if platform.system() == "Darwin":
            os.environ.setdefault("BRAIN_DIFF_LLAMA_ON_CPU", "1")

        apply_huggingface_text_mps_dtype_patch()

        requested = detect_runtime_profile()
        self._configure_whisper_defaults(requested)
        last_err: Exception | None = None
        for device in requested.fallback_chain:
            profile = requested if device == requested.device else _profile_for_device(device)
            try:
                logger.info("TribeService.load:attempt device=%s backend=%s", profile.device, profile.backend)
                self.model = TribeModel.from_pretrained(
                    self.model_revision,
                    cache_folder=self.cache_folder,
                    device=profile.device,
                    config_update=profile.config_update,
                )
                self.runtime_profile = profile
                logger.info("TribeService.load:ok device=%s backend=%s", profile.device, profile.backend)
                return
            except Exception as err:
                last_err = err
                logger.warning("TribeService.load:attempt_failed device=%s err=%s", profile.device, err, exc_info=True)
        raise RuntimeError(f"Failed to load model {self.model_revision}: {last_err}") from last_err

    @staticmethod
    def _configure_whisper_defaults(profile: RuntimeProfile) -> None:
        if profile.device == "cuda":
            return
        if profile.device == "mps":
            # TRIBEv2 uses MPS/accelerate; WhisperX (CTranslate2) has no MPS — force CPU for subprocess.
            os.environ.setdefault("TRIBEV2_WHISPERX_DEVICE", "cpu")
            os.environ.setdefault("TRIBEV2_WHISPERX_BATCH_SIZE", "8")
            os.environ.setdefault("TRIBEV2_WHISPERX_ALIGN_MODEL", "WAV2VEC2_ASR_LARGE_LV60K_960H")
            return
        # Actual CPU-only fallback: lighter Whisper defaults
        os.environ.setdefault("TRIBEV2_WHISPERX_MODEL", "tiny.en")
        os.environ.setdefault("TRIBEV2_WHISPERX_BATCH_SIZE", "4")
        os.environ.setdefault("TRIBEV2_WHISPERX_ALIGN_MODEL", "WAV2VEC2_ASR_LARGE_LV60K_960H")

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
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{ffmpeg_dir}:{os.environ.get('PATH', '')}"

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
