import logging
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

logger = logging.getLogger("braindiff.test_model_smoke")


def _ensure_uvx_path() -> None:
    bin_dir = Path(sys.executable).parent
    uvx_bin = bin_dir / "uvx"
    if uvx_bin.exists():
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"


# ---------------------------------------------------------------------------
# Primary smoke path: TribeService.load() + text_to_predictions()
# ---------------------------------------------------------------------------


def test_tribe_service_smoke(monkeypatch):
    """Primary smoke: instantiate TribeService, load(), then text_to_predictions().

    Uses a stub TribeModel so no weights are required.
    """
    monkeypatch.setenv("BRAIN_DIFF_SKIP_STARTUP", "1")
    monkeypatch.setenv("BRAIN_DIFF_DEVICE", "cpu")

    fake_preds = np.zeros((4, 20484), dtype=np.float32)
    fake_preds[:, :10] = 0.5

    class _FakeModel:
        def get_events_dataframe(self, text_path):
            return pd.DataFrame([{"type": "text", "start": 0.0}])

        def predict(self, events):
            return fake_preds, []

    class _FakeTribeModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            return _FakeModel()

    # Patch both import paths that TribeService tries.
    with (
        patch("backend.model_service.apply_huggingface_text_mps_dtype_patch"),
        patch.dict("sys.modules", {"tribev2": MagicMock(TribeModel=_FakeTribeModel)}),
    ):
        from backend.model_service import TribeService

        svc = TribeService(model_revision="facebook/tribev2", cache_folder="./cache")
        svc.load()

        assert svc.model is not None
        assert svc.runtime_profile is not None
        assert svc.text_backend_strategy is not None

        preds, segments, timing = svc.text_to_predictions("Hello world.")
        assert preds.shape == (4, 20484)
        assert isinstance(timing, dict)
        assert "events_ms" in timing
        assert "predict_ms" in timing


# ---------------------------------------------------------------------------
# Slow full-predict smoke (gated behind TRIBEV2_E2E_PREDICT=1)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("TRIBEV2_E2E_PREDICT", "") != "1",
    reason="Full TRIBEv2 predict + WhisperX: set TRIBEV2_E2E_PREDICT=1 (slow).",
)
def test_model_loads_and_predicts() -> None:
    _ensure_uvx_path()

    def _tribe_model_class():
        try:
            from tribev2 import TribeModel as TM  # type: ignore
            return TM
        except ImportError:
            pass
        try:
            from tribev2.demo_utils import TribeModel as TM  # type: ignore
            return TM
        except ImportError:
            pytest.skip("tribev2 not installed in this environment")

    TribeModel = _tribe_model_class()
    logger.info("Loading TRIBEv2 model...")
    model = TribeModel.from_pretrained("facebook/tribev2", cache_folder="./cache")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as handle:
        handle.write("The quick brown fox jumps over the lazy dog.")
        temp_path = handle.name
    fallback_audio_path = None

    try:
        try:
            df = model.get_events_dataframe(text_path=temp_path)
        except Exception as err:
            msg = str(err).lower()
            if "whisperx failed" in msg or "ffmpeg" in msg or "'uvx'" in msg or "no such file or directory: 'uvx'" in msg:
                logger.warning("Text smoke path unavailable; using audio-only fallback")
                df, fallback_audio_path = _audio_only_events_fallback()
            else:
                raise

        preds, segments = model.predict(events=df)
        if hasattr(preds, "detach"):
            preds = preds.detach().cpu().numpy()
        elif hasattr(preds, "values"):
            preds = preds.values
        preds = np.array(preds, dtype=np.float32)

        assert preds.shape[1] == 20484
        assert preds.shape[0] > 0
    finally:
        os.unlink(temp_path)
        if fallback_audio_path and os.path.exists(fallback_audio_path):
            os.unlink(fallback_audio_path)


def _audio_only_events_fallback() -> tuple[pd.DataFrame, str]:
    from scipy.io.wavfile import write as wavwrite
    from tribev2.demo_utils import get_audio_and_text_events

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        wav_path = handle.name
    sr = 16000
    t = np.linspace(0.0, 2.0, int(sr * 2.0), endpoint=False)
    waveform = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    wavwrite(wav_path, sr, waveform)
    base_events = pd.DataFrame([
        {"type": "Audio", "filepath": wav_path, "start": 0.0, "timeline": "default", "subject": "default"}
    ])
    return get_audio_and_text_events(base_events, audio_only=True), wav_path
