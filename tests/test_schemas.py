import pytest
from pydantic import ValidationError

from backend.schemas import DiffRequest


def test_text_only_request_still_valid():
    req = DiffRequest(text_a="Hello world.", text_b="Goodbye world.")
    assert req.modality() == "text"


def test_audio_request_uses_audio_paths():
    req = DiffRequest(audio_path_a="/tmp/a.wav", audio_path_b="/tmp/b.wav")
    assert req.modality() == "audio"


def test_video_request_uses_video_paths():
    req = DiffRequest(video_path_a="/tmp/a.mp4", video_path_b="/tmp/b.mp4")
    assert req.modality() == "video"


def test_mixed_modality_rejected():
    with pytest.raises(ValidationError):
        DiffRequest(text_a="Hello.", audio_path_b="/tmp/b.wav")


def test_missing_pair_rejected():
    with pytest.raises(ValidationError):
        DiffRequest(text_a="Hello.")


def test_no_inputs_rejected():
    with pytest.raises(ValidationError):
        DiffRequest()
