from __future__ import annotations

import json
import os
import subprocess

MAX_MEDIA_SECONDS: int = 30
MEDIA_SIMILARITY_SECONDS: int = 5
TEXT_SIMILARITY_CHARS: int = 20


class DurationMismatch(ValueError):
    pass


class DurationProbeError(RuntimeError):
    pass


def _run_ffprobe_duration(path: str) -> float | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        path,
    ]
    try:
        raw = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        payload = json.loads(raw)
        duration_value = payload.get("format", {}).get("duration")
        if duration_value is None:
            return None
        duration = float(duration_value)
        if duration < 0:
            return None
        return duration
    except FileNotFoundError:
        return None
    except (subprocess.CalledProcessError, ValueError, json.JSONDecodeError):
        return None


def _run_ffmpeg_duration(path: str) -> float | None:
    try:
        proc = subprocess.run(["ffmpeg", "-i", path], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    for line in proc.stderr.splitlines():
        stripped = line.strip()
        if not stripped.startswith("Duration:"):
            continue
        try:
            hms = stripped.split("Duration:", 1)[1].split(",", 1)[0].strip()
            h, m, s = hms.split(":")
            duration = int(h) * 3600 + int(m) * 60 + float(s)
            if duration < 0:
                return None
            return duration
        except (ValueError, IndexError):
            return None
    return None


def probe_duration_seconds(path: str) -> float:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    ffprobe_duration = _run_ffprobe_duration(path)
    if ffprobe_duration is not None:
        return ffprobe_duration
    ffmpeg_duration = _run_ffmpeg_duration(path)
    if ffmpeg_duration is not None:
        return ffmpeg_duration
    raise DurationProbeError(f"Could not read duration from media file: {path}")


def ensure_within_max(path: str, *, max_seconds: int = MAX_MEDIA_SECONDS) -> tuple[str, float, bool]:
    duration = probe_duration_seconds(path)
    if duration <= max_seconds:
        return path, duration, False
    root, ext = os.path.splitext(path)
    trimmed_path = f"{root}.trim{ext}"
    copy_cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "0",
        "-i",
        path,
        "-t",
        str(max_seconds),
        "-c",
        "copy",
        trimmed_path,
    ]
    try:
        subprocess.check_call(copy_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        recode_cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            "0",
            "-i",
            path,
            "-t",
            str(max_seconds),
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            trimmed_path,
        ]
        subprocess.check_call(recode_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return trimmed_path, float(max_seconds), True


def check_media_similarity(
    seconds_a: float,
    seconds_b: float,
    *,
    tolerance: int = MEDIA_SIMILARITY_SECONDS,
) -> None:
    delta = abs(seconds_a - seconds_b)
    if delta > tolerance:
        raise DurationMismatch(
            f"Stimuli durations differ by {delta:.1f}s ({seconds_a:.1f}s vs {seconds_b:.1f}s). "
            f"Both stimuli must be within {tolerance}s of each other."
        )


def check_text_similarity(
    text_a: str,
    text_b: str,
    *,
    tolerance: int = TEXT_SIMILARITY_CHARS,
) -> None:
    delta = abs(len(text_a) - len(text_b))
    if delta > tolerance:
        raise DurationMismatch(
            f"Text lengths differ by {delta} characters ({len(text_a)} vs {len(text_b)}). "
            f"Both stimuli must be within {tolerance} characters of each other."
        )
