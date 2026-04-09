import logging
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

logger = logging.getLogger("braindiff.test_model_smoke")


def _ensure_uvx_path() -> None:
    bin_dir = Path(sys.executable).parent
    uvx_bin = bin_dir / "uvx"
    if uvx_bin.exists():
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"


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


def test_tribe_model_loads_from_hub() -> None:
    """Fast check: checkpoint + weights load (no WhisperX / predict)."""
    TribeModel = _tribe_model_class()
    model = TribeModel.from_pretrained("facebook/tribev2", cache_folder="./cache")
    assert model._model is not None


@pytest.mark.skipif(
    os.environ.get("TRIBEV2_E2E_PREDICT", "") != "1",
    reason="Full TRIBEv2 predict + WhisperX: set TRIBEV2_E2E_PREDICT=1 (slow).",
)
def test_model_loads_and_predicts() -> None:
    _ensure_uvx_path()
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
