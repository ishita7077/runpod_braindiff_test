import logging
import os
import tempfile

import numpy as np
import pandas as pd

logger = logging.getLogger("braindiff.test_model_smoke")

CPU_CONFIG_UPDATE = {
    "data.audio_feature.device": "cpu",
    "data.text_feature.device": "cpu",
    "data.image_feature.image.device": "cpu",
    "data.video_feature.image.device": "cpu",
    "data.audio_feature.infra.gpus_per_node": 0,
    "data.text_feature.infra.gpus_per_node": 0,
    "data.image_feature.infra.gpus_per_node": 0,
    "data.video_feature.infra.gpus_per_node": 0,
}


def test_model_loads_and_predicts() -> None:
    try:
        from tribev2 import TribeModel
    except ImportError:
        from tribev2.demo_utils import TribeModel

    logger.info("Loading TRIBEv2 model...")
    model = TribeModel.from_pretrained(
        "facebook/tribev2",
        cache_folder="./cache",
        device="cpu",
        config_update=CPU_CONFIG_UPDATE,
    )
    logger.info("Model loaded successfully")

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
                logger.warning("Text smoke path unavailable (missing ffmpeg/whisperx deps), using audio-only fallback")
                df, fallback_audio_path = _audio_only_events_fallback()
            else:
                raise
        logger.info("Events dataframe created with %s rows", len(df))

        preds, segments = model.predict(events=df)
        if hasattr(preds, "detach"):
            preds = preds.detach().cpu().numpy()
        elif hasattr(preds, "values"):
            preds = preds.values
        preds = np.array(preds, dtype=np.float32)

        logger.info("Predictions shape=%s, segments_type=%s", preds.shape, type(segments).__name__)
        assert preds.shape[1] == 20484, f"Wrong vertex count: {preds.shape[1]}"
        assert preds.shape[0] > 0, "Zero timesteps"
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
    base_events = pd.DataFrame(
        [
            {
                "type": "Audio",
                "filepath": wav_path,
                "start": 0.0,
                "timeline": "default",
                "subject": "default",
            }
        ]
    )
    return get_audio_and_text_events(base_events, audio_only=True), wav_path

