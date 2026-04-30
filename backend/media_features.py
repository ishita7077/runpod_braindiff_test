"""Real audio/video features for the result pages.

The audio + video result pages need three things the worker did not previously
extract:

1. A real audio amplitude envelope (so the audio waveform isn't two unrelated
   cortical timeseries glued together).
2. Real keyframe thumbnails for the video, sampled at scene-change boundaries
   when ffmpeg's scdet filter finds them, with a uniform fallback otherwise.
3. Real per-timestep peak-Δ moment detection on the cortical contrast — top-K
   timestamps where `vertex_delta` magnitude peaks, attributed to the
   driving dimension and side. (This replaces the `buildMoments()` template
   in media-results.js that fabricated identical "{label} changes at beat N"
   prose for every job.)

All three are best-effort: if ffmpeg/ffprobe fails or files are corrupt,
return empty rather than fake. Result pages render an empty state when the
relevant feature is empty — far better than `Math.sin(x*3.4 + y*4.1)`.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import struct
import subprocess
import tempfile
from typing import Any

import numpy as np

logger = logging.getLogger("braindiff.media_features")

# Audio waveform: ~200 RMS bins gives smooth scrubbable timeline without
# inflating the result payload. At 30 s max media duration, that's one bin
# per ~150 ms — finer than human pause perception, coarser than per-sample.
WAVEFORM_BINS = 200

# Video keyframes: 6 frames sampled at scene boundaries (or uniformly) keep
# payload size manageable while letting the result page show a real strip
# of what was analysed. Each thumb is 240 × 135 px, JPEG-base64.
KEYFRAME_COUNT = 6
KEYFRAME_WIDTH = 240
KEYFRAME_HEIGHT = 135


def _ffmpeg_path() -> str | None:
    """Find ffmpeg on PATH (worker uses imageio_ffmpeg shim)."""
    return shutil.which("ffmpeg")


def _ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def audio_envelope(path: str, *, bins: int = WAVEFORM_BINS) -> list[float]:
    """Compute an amplitude envelope of the audio track at `path`.

    Decodes mono PCM s16le via ffmpeg (works for any audio/video file), then
    folds the samples into `bins` RMS buckets and normalises to [0, 1] so the
    result page can render bars directly. Returns [] if ffmpeg isn't
    available or the file can't be decoded.

    Why RMS instead of peak: peak amplitude is dominated by spurious clicks
    on cheap recordings, and we want the visual to track perceived loudness.
    """
    ffmpeg = _ffmpeg_path()
    if ffmpeg is None or not os.path.isfile(path):
        return []
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-v", "error",
                "-i", path,
                "-vn",                # ignore video stream if present
                "-ac", "1",           # mono
                "-ar", "16000",       # 16 kHz — plenty for an envelope
                "-f", "s16le",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
        logger.warning("audio_envelope: ffmpeg failed for %s: %s", path, err)
        return []
    raw = proc.stdout
    if not raw:
        return []
    sample_count = len(raw) // 2
    if sample_count == 0:
        return []
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if bins <= 0 or bins >= sample_count:
        bins = max(1, min(WAVEFORM_BINS, sample_count))
    # Bucket boundaries — last bucket gets the remainder.
    step = sample_count / bins
    out = np.empty(bins, dtype=np.float32)
    for i in range(bins):
        start = int(round(i * step))
        end = int(round((i + 1) * step)) if i < bins - 1 else sample_count
        if end <= start:
            out[i] = 0.0
            continue
        chunk = samples[start:end]
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        out[i] = rms
    peak = float(out.max())
    if peak <= 1e-9:
        return [0.0] * bins
    out /= peak
    return [round(float(v), 4) for v in out]


def detect_scene_boundaries(
    path: str, *, threshold: float = 0.35, max_count: int = KEYFRAME_COUNT
) -> list[float]:
    """Return a sorted list of scene-change timestamps (seconds) found by
    ffmpeg's scdet filter, capped to `max_count`.

    Honest behaviour: if scdet finds fewer than `max_count` boundaries, the
    list is shorter — callers should pad to a uniform sampling for keyframes
    rather than inventing scene boundaries that don't exist.
    """
    ffmpeg = _ffmpeg_path()
    if ffmpeg is None or not os.path.isfile(path):
        return []
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-v", "info",
                "-i", path,
                "-vf", f"scdet=t={threshold}",
                "-f", "null",
                "-",
            ],
            check=False,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as err:
        logger.warning("detect_scene_boundaries: ffmpeg timed out on %s: %s", path, err)
        return []
    boundaries: list[float] = []
    # scdet logs lines like: "[Parsed_scdet_0 @ 0x...] lavfi.scd.score: 0.41 lavfi.scd.time: 7.234"
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        if "lavfi.scd.time" not in line:
            continue
        try:
            tail = line.split("lavfi.scd.time:", 1)[1].strip()
            ts = float(tail.split()[0])
            boundaries.append(round(ts, 2))
        except (ValueError, IndexError):
            continue
    boundaries.sort()
    if len(boundaries) <= max_count:
        return boundaries
    # If we got more than we want, keep the first, last, and evenly spaced
    # interior boundaries so the keyframe strip spans the whole clip.
    idxs = np.linspace(0, len(boundaries) - 1, max_count).round().astype(int)
    return [boundaries[i] for i in idxs]


def _probe_duration(path: str) -> float:
    """Cheap duration probe — used to fall back to uniform keyframe sampling
    when scdet returns nothing."""
    ffprobe = _ffprobe_path()
    if ffprobe is None:
        return 0.0
    try:
        proc = subprocess.run(
            [
                ffprobe, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                path,
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )
        payload = json.loads(proc.stdout.decode("utf-8", "replace"))
        return float(payload.get("format", {}).get("duration") or 0.0)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        return 0.0


def video_keyframes(
    path: str,
    *,
    count: int = KEYFRAME_COUNT,
    width: int = KEYFRAME_WIDTH,
    height: int = KEYFRAME_HEIGHT,
) -> list[dict[str, Any]]:
    """Extract `count` keyframe thumbnails from the video at `path`.

    Strategy: detect scene-change timestamps with scdet; if scdet returns
    fewer than `count`, fall back to uniform sampling. Each thumbnail is
    resized to `width` × `height`, JPEG-encoded, and base64-embedded into
    the result so the page is self-contained (no second fetch, no need to
    keep the original blob alive).

    Returns a list of `{"time": float_seconds, "image_base64": str}`.
    Returns [] when ffmpeg is missing or the video can't be decoded.
    """
    ffmpeg = _ffmpeg_path()
    if ffmpeg is None or not os.path.isfile(path):
        return []
    duration = _probe_duration(path)
    if duration <= 0:
        return []
    scene_ts = detect_scene_boundaries(path, max_count=count)
    if len(scene_ts) < count:
        # Pad with uniform samples between 5% and 95% of duration so we don't
        # land on the title card on either end. Merge with scene timestamps
        # and dedupe within 0.5 s.
        uniform = list(np.linspace(0.05 * duration, 0.95 * duration, count).round(2))
        merged = sorted(set([round(t, 2) for t in scene_ts] + [round(t, 2) for t in uniform]))
        # Trim to `count` while keeping spread.
        if len(merged) > count:
            idxs = np.linspace(0, len(merged) - 1, count).round().astype(int)
            merged = [merged[i] for i in idxs]
        timestamps = merged
    else:
        timestamps = scene_ts[:count]
    out: list[dict[str, Any]] = []
    for ts in timestamps:
        encoded = _extract_frame_b64(path, ts, width, height)
        if encoded is None:
            continue
        out.append({"time": float(round(ts, 2)), "image_base64": encoded})
    return out


def _extract_frame_b64(path: str, ts: float, width: int, height: int) -> str | None:
    ffmpeg = _ffmpeg_path()
    if ffmpeg is None:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            out_path = handle.name
        # Seek before -i is much faster (key-frame seek), then a precise
        # forward seek with -ss after -i to land on the requested time.
        proc = subprocess.run(
            [
                ffmpeg, "-v", "error", "-y",
                "-ss", str(max(0.0, ts - 1.0)),
                "-i", path,
                "-ss", str(min(1.0, ts)),
                "-frames:v", "1",
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
                "-q:v", "5",
                out_path,
            ],
            check=False,
            capture_output=True,
            timeout=15,
        )
        if proc.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            return None
        with open(out_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except subprocess.TimeoutExpired:
        return None
    finally:
        try:
            os.unlink(out_path)
        except (OSError, NameError):
            pass


def peak_moments(
    preds_a: np.ndarray,
    preds_b: np.ndarray,
    masks: dict[str, dict[str, Any]],
    *,
    duration_seconds: float | None = None,
    top_k: int = 4,
) -> list[dict[str, Any]]:
    """Find the top-K timesteps where the per-dimension B−A contrast peaks,
    and label each one with the dimension that drove it and the side ("A" or
    "B") that's stronger there.

    This replaces the templated `buildMoments()` in media-results.js. Each
    returned moment carries:
      - `time` (seconds, mapped from timestep using `duration_seconds`),
      - `sample` ("A" or "B"),
      - `track` (dimension key, e.g. "attention_salience"),
      - `delta` (signed contrast at the peak),
      - `magnitude` (|delta|),
      - `timestep` (raw integer index, useful for joining to per-timestep
        cortical paint).

    Frontend renders: title from dimension + sample, detail computed from
    `delta`. No fake prose.
    """
    if preds_a.ndim != 2 or preds_b.ndim != 2:
        return []
    timesteps = min(preds_a.shape[0], preds_b.shape[0])
    if timesteps == 0 or not masks:
        return []
    # Per-timestep, per-dimension mean activation. (timesteps, n_dims).
    dim_keys = list(masks.keys())
    ts_a = np.zeros((timesteps, len(dim_keys)), dtype=np.float32)
    ts_b = np.zeros((timesteps, len(dim_keys)), dtype=np.float32)
    for j, key in enumerate(dim_keys):
        mask = masks[key].get("mask")
        if mask is None or not np.any(mask):
            continue
        ts_a[:, j] = preds_a[:timesteps, mask].mean(axis=1)
        ts_b[:, j] = preds_b[:timesteps, mask].mean(axis=1)
    delta = ts_b - ts_a  # (timesteps, n_dims)
    if delta.size == 0:
        return []
    # Greedy top-K with a non-maximum-suppression window: pick the largest
    # |delta|, blank out a ±2-timestep neighbourhood, repeat. Otherwise the
    # top-4 cluster on the same peak and the user sees four redundant cards.
    abs_delta = np.abs(delta)
    used = np.zeros(timesteps, dtype=bool)
    moments: list[dict[str, Any]] = []
    for _ in range(top_k):
        candidate_max = -1.0
        best_t, best_d = -1, -1
        for t in range(timesteps):
            if used[t]:
                continue
            row = abs_delta[t]
            d_max_idx = int(row.argmax())
            d_max = float(row[d_max_idx])
            if d_max > candidate_max:
                candidate_max = d_max
                best_t, best_d = t, d_max_idx
        if best_t < 0 or candidate_max <= 0:
            break
        signed = float(delta[best_t, best_d])
        time_seconds = (
            float(duration_seconds) * (best_t / max(timesteps - 1, 1))
            if duration_seconds is not None and duration_seconds > 0
            else float(best_t)
        )
        moments.append({
            "time": round(time_seconds, 2),
            "timestep": int(best_t),
            "sample": "B" if signed >= 0 else "A",
            "track": dim_keys[best_d],
            "delta": round(signed, 5),
            "magnitude": round(abs(signed), 5),
        })
        # Suppression window: ±2 timesteps to spread moments across the run.
        lo = max(0, best_t - 2)
        hi = min(timesteps, best_t + 3)
        used[lo:hi] = True
    moments.sort(key=lambda m: m["time"])
    return moments
