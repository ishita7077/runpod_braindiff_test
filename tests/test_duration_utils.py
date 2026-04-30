import os
import subprocess

import pytest

from backend.duration_utils import (
    DurationMismatch,
    MAX_MEDIA_SECONDS,
    MEDIA_SIMILARITY_SECONDS,
    TEXT_SIMILARITY_CHARS,
    check_media_similarity,
    check_text_similarity,
    ensure_within_max,
    probe_duration_seconds,
    trim_to_duration,
)


def test_probe_duration_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        probe_duration_seconds("/nonexistent/file.mp3")


def test_text_similarity_accepts_close_lengths():
    check_text_similarity("a" * 100, "b" * 115)


def test_text_similarity_rejects_far_lengths():
    with pytest.raises(DurationMismatch) as exc:
        check_text_similarity("a" * 100, "b" * 150)
    assert "20" in str(exc.value) or "characters" in str(exc.value).lower()


def test_media_similarity_accepts_within_5_seconds():
    check_media_similarity(28.0, 30.0)


def test_media_similarity_rejects_over_5_seconds():
    with pytest.raises(DurationMismatch) as exc:
        check_media_similarity(10.0, 28.0)
    assert "5" in str(exc.value) or "similar" in str(exc.value).lower()


def test_constants_match_product_rules():
    assert MAX_MEDIA_SECONDS == 30
    assert MEDIA_SIMILARITY_SECONDS == 5
    assert TEXT_SIMILARITY_CHARS == 20


@pytest.mark.skipif(
    not bool(subprocess.run(["which", "ffmpeg"], capture_output=True, text=True).stdout.strip()),
    reason="ffmpeg not available",
)
def test_ensure_within_max_trims_long_wav(tmp_path):
    src = tmp_path / "long.wav"
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.2",
            str(src),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    out_path, duration_seconds, was_trimmed = ensure_within_max(str(src), max_seconds=1)
    assert was_trimmed is True
    assert out_path != str(src)
    assert os.path.exists(out_path)
    assert duration_seconds == 1.0


@pytest.mark.skipif(
    not bool(subprocess.run(["which", "ffmpeg"], capture_output=True, text=True).stdout.strip()),
    reason="ffmpeg not available",
)
def test_trim_to_duration_cuts_wav_to_requested_length(tmp_path):
    src = tmp_path / "long.wav"
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.6",
            str(src),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    out_path = trim_to_duration(str(src), 0.7)
    assert out_path != str(src)
    assert os.path.exists(out_path)
    assert probe_duration_seconds(out_path) <= 0.9
