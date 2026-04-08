import logging
import os
import shutil
import sys
import tempfile
from typing import Any

import numpy as np
import torch

logger = logging.getLogger("braindiff.model_service")


class TribeService:
    def __init__(self, model_revision: str = "facebook/tribev2", cache_folder: str = "./cache") -> None:
        self.model_revision = model_revision
        self.cache_folder = cache_folder
        self.model = None

    def load(self) -> None:
        logger.info("TribeService.load:start model_revision=%s", self.model_revision)
        self._ensure_uvx_on_path()
        self._ensure_ffmpeg_on_path()
        self._configure_cpu_whisperx_defaults()
        try:
            try:
                from tribev2 import TribeModel  # type: ignore
            except ImportError:
                from tribev2.demo_utils import TribeModel  # type: ignore
        except Exception as err:
            raise RuntimeError("Failed to import TRIBEv2. Install facebookresearch/tribev2 first.") from err

        cpu_config_update = {
            "data.audio_feature.device": "cpu",
            "data.text_feature.device": "cpu",
            "data.image_feature.image.device": "cpu",
            "data.video_feature.image.device": "cpu",
            "data.audio_feature.infra.gpus_per_node": 0,
            "data.text_feature.infra.gpus_per_node": 0,
            "data.image_feature.infra.gpus_per_node": 0,
            "data.video_feature.infra.gpus_per_node": 0,
        }
        try:
            self.model = TribeModel.from_pretrained(
                self.model_revision,
                cache_folder=self.cache_folder,
                device="cpu",
                config_update=cpu_config_update,
            )
        except Exception as err:
            raise RuntimeError(f"Failed to load model {self.model_revision}") from err
        logger.info("TribeService.load:ok")

    @staticmethod
    def _configure_cpu_whisperx_defaults() -> None:
        # Keep canonical behavior on GPU. On CPU, prefer a practical local profile.
        if torch.cuda.is_available():
            return
        if "TRIBEV2_WHISPERX_MODEL" not in os.environ:
            os.environ["TRIBEV2_WHISPERX_MODEL"] = "tiny.en"
        if "TRIBEV2_WHISPERX_BATCH_SIZE" not in os.environ:
            os.environ["TRIBEV2_WHISPERX_BATCH_SIZE"] = "4"
        if "TRIBEV2_WHISPERX_ALIGN_MODEL" not in os.environ:
            os.environ["TRIBEV2_WHISPERX_ALIGN_MODEL"] = "WAV2VEC2_ASR_LARGE_LV60K_960H"
        logger.info(
            "whisperx cpu defaults model=%s batch=%s align_model=%s",
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
            events = self.model.get_events_dataframe(text_path=temp_path)
            preds, segments = self.model.predict(events=events)
            if hasattr(preds, "detach"):
                preds = preds.detach().cpu().numpy()
            elif hasattr(preds, "values"):
                preds = preds.values
            preds_np = np.array(preds, dtype=np.float32)
            if preds_np.ndim != 2:
                raise ValueError(f"Unexpected predictions shape: {preds_np.shape}")
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
                    "FFMPEG_REQUIRED: uv/uvx is required for text->speech transcription path."
                ) from err
            raise
        finally:
            os.unlink(temp_path)

