import logging
import os
import shutil
import sys
import tempfile
import time
from typing import Any

import numpy as np
import torch

logger = logging.getLogger("braindiff.model_service")


class TribeService:
    def __init__(self, model_revision: str = "facebook/tribev2", cache_folder: str = "./cache") -> None:
        self.model_revision = model_revision
        self.cache_folder = cache_folder
        self.model = None
        self.runtime_info: dict[str, Any] = {
            "requested_device": os.getenv("BRAIN_DIFF_DEVICE", "auto"),
            "selected_device": None,
            "load_attempts": [],
        }

    @staticmethod
    def _mps_available() -> bool:
        return bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())

    def _device_candidates(self) -> list[str]:
        forced = os.getenv("BRAIN_DIFF_DEVICE", "auto").strip().lower()
        if forced and forced != "auto":
            return [forced]
        if torch.cuda.is_available():
            return ["cuda", "cpu"]
        return ["cpu"]

    @staticmethod
    def _config_for_device(device: str) -> dict[str, Any]:
        feature_device = "cuda" if device == "cuda" else "cpu"
        gpus = 1 if device == "cuda" else 0
        config = {
            "data.audio_feature.device": feature_device,
            "data.text_feature.device": feature_device,
            "data.image_feature.image.device": feature_device,
            "data.video_feature.image.device": feature_device,
            "data.audio_feature.infra.gpus_per_node": gpus,
            "data.text_feature.infra.gpus_per_node": gpus,
            "data.image_feature.infra.gpus_per_node": gpus,
            "data.video_feature.infra.gpus_per_node": gpus,
        }
        return config

    def load(self) -> None:
        logger.info("TribeService.load:start model_revision=%s", self.model_revision)
        self._ensure_uvx_on_path()
        self._ensure_ffmpeg_on_path()
        self._configure_local_whisperx_defaults()
        try:
            try:
                from tribev2 import TribeModel  # type: ignore
            except ImportError:
                from tribev2.demo_utils import TribeModel  # type: ignore
        except Exception as err:
            raise RuntimeError("Failed to import TRIBEv2. Install facebookresearch/tribev2 first.") from err

        last_err: Exception | None = None
        for device in self._device_candidates():
            config_update = self._config_for_device(device)
            attempt = {"device": device, "config_update": config_update}
            t0 = time.perf_counter()
            try:
                logger.info("TribeService.load:attempt device=%s", device)
                self.model = TribeModel.from_pretrained(
                    self.model_revision,
                    cache_folder=self.cache_folder,
                    device=device,
                    config_update=config_update,
                )
                attempt["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
                attempt["ok"] = True
                self.runtime_info["selected_device"] = device
                self.runtime_info["load_attempts"].append(attempt)
                logger.info("TribeService.load:ok device=%s elapsed_ms=%s", device, attempt["elapsed_ms"])
                return
            except Exception as err:
                attempt["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
                attempt["ok"] = False
                attempt["error"] = str(err)
                self.runtime_info["load_attempts"].append(attempt)
                logger.warning("TribeService.load:failed device=%s error=%s", device, err)
                last_err = err
                self.model = None
        raise RuntimeError(f"Failed to load model {self.model_revision}") from last_err

    @staticmethod
    def _configure_local_whisperx_defaults() -> None:
        # Keep canonical behavior on GPU. On local/dev paths prefer a practical profile.
        if torch.cuda.is_available():
            return
        defaults = {
            "TRIBEV2_WHISPERX_MODEL": "tiny.en",
            "TRIBEV2_WHISPERX_BATCH_SIZE": "4",
            "TRIBEV2_WHISPERX_ALIGN_MODEL": "WAV2VEC2_ASR_LARGE_LV60K_960H",
        }
        for key, value in defaults.items():
            os.environ.setdefault(key, value)
        logger.info(
            "whisperx local defaults model=%s batch=%s align_model=%s",
            os.environ.get("TRIBEV2_WHISPERX_MODEL"),
            os.environ.get("TRIBEV2_WHISPERX_BATCH_SIZE"),
            os.environ.get("TRIBEV2_WHISPERX_ALIGN_MODEL", ""),
        )

    @staticmethod
    def _ensure_uvx_on_path() -> None:
        if shutil.which("uvx"):
            return
        py_bin = os.path.dirname(sys.executable)
        uvx_candidate = os.path.join(py_bin, "uvx")
        if os.path.exists(uvx_candidate):
            os.environ["PATH"] = f"{py_bin}:{os.environ.get('PATH', '')}"
            logger.info("uvx configured from python bin dir: %s", uvx_candidate)

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
        logger.info("ffmpeg configured via imageio_ffmpeg at %s", ffmpeg_exe)

    def text_to_predictions(self, text: str) -> tuple[np.ndarray, Any]:
        if self.model is None:
            raise RuntimeError("TRIBEv2 model not loaded")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as handle:
            handle.write(text)
            temp_path = handle.name

        try:
            t0 = time.perf_counter()
            events = self.model.get_events_dataframe(text_path=temp_path)
            events_ms = int((time.perf_counter() - t0) * 1000)
            logger.info("text_to_predictions:events_created ms=%s chars=%s", events_ms, len(text))

            t1 = time.perf_counter()
            preds, segments = self.model.predict(events=events)
            pred_ms = int((time.perf_counter() - t1) * 1000)
            logger.info("text_to_predictions:predicted ms=%s chars=%s", pred_ms, len(text))

            if hasattr(preds, "detach"):
                preds = preds.detach().cpu().numpy()
            elif hasattr(preds, "values"):
                preds = preds.values
            preds_np = np.array(preds, dtype=np.float32)
            if preds_np.ndim != 2:
                raise ValueError(f"Unexpected predictions shape: {preds_np.shape}")
            logger.info("text_to_predictions:ok shape=%s device=%s", preds_np.shape, self.runtime_info.get("selected_device"))
            return preds_np, segments
        except Exception as err:
            msg = str(err)
            if "gated repo" in msg or "meta-llama/Llama-3.2-3B" in msg or "401 Client Error" in msg:
                raise RuntimeError(
                    "HF_AUTH_REQUIRED: Access to meta-llama/Llama-3.2-3B is required. "
                    "Run `huggingface-cli login` in this environment with an approved token."
                ) from err
            if "ffmpeg" in msg.lower():
                raise RuntimeError(
                    "FFMPEG_REQUIRED: ffmpeg is required for text->speech transcription path."
                ) from err
            if "'uvx'" in msg or "No such file or directory: 'uvx'" in msg:
                raise RuntimeError(
                    "UVX_REQUIRED: uv/uvx is required for text->speech transcription path."
                ) from err
            raise
        finally:
            os.unlink(temp_path)
