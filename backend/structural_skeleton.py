"""Structural Skeleton — when the *content* changes across text, audio, video.

This is the deliberately-trimmed v1 of "Prompt 1" (Foundation Model
Intermediate Outputs / Structural Skeleton). It uses only the data the
worker already produces — transcript segments, audio waveform, video
keyframes — to surface three lanes of content-change events plus a
cross-modal alignment score.

What this v1 does NOT do (deferred to v2 — see methodology-skeleton.html):
  - access TRIBE v2's intermediate LLaMA / V-JEPA2 / Wav2Vec-BERT
    embeddings to detect topic / scene / audio events. Those are
    cached on disk by `neuralset.extractors` during prediction but
    surfacing them through the worker requires plumbing changes that
    are a separate research-shaped project.
  - run a 4-class audio classifier (speech / music / silence / noise).
    Needs a labelled training corpus we do not have. Energy-based
    detection covers the common case for now.
  - generate per-shift "before/after" 6-word summaries via a local
    LLaMA call. Adds inference cost + plumbing for marginal value
    over the first / last sentence of each segment, which is free.

What this v1 DOES do, transparently:

  TEXT EVENTS — from meta.transcript_segments_a/b
    • TF-IDF cosine distance between consecutive WhisperX-aligned
      phrases. Shift = distance > 0.55 (English text, conservative
      because WhisperX phrases are short and noisy on segment 1).
      Each event carries the segment text on either side as
      before_summary / after_summary — the actual phrases the user
      heard, not an invented LLM summary.

  AUDIO EVENTS — from meta.media_features.waveform_a/b (200 RMS bins)
    • Energy spikes: bins whose RMS > local mean + 2.5 std.
    • Long silences: runs of bins with RMS < 0.05 lasting 1+ s.

  VISUAL EVENTS — from meta.media_features.keyframes_a/b
    • Scene cuts at keyframe timestamps. Magnitude = the keyframe
      density (more keyframes / second = more cuts).

  ALIGNMENT — for each pair of (text, visual, audio) lanes, count
  events that occur within 1.0 second of each other across modalities.
  alignment_score = aligned_events / total_events.

Output shape (per side):
{
  "text_events":   [{time, type, score, before_summary, after_summary}],
  "visual_events": [{time, type, score, magnitude}],
  "audio_events":  [{time, type, score}],
  "alignment": {
    "cross_modal_alignment_score": float (0–1),
    "aligned_moments":   [{time, modalities: [...]}],
    "misaligned_moments":[{time, leading_modality, lag_seconds}]
  },
  "summary_line": "X topic shifts · Y scene cuts · Z audio transitions · alignment 0.NN"
}

Returned per-side under meta.media_features.skeleton.{a, b}.
"""
from __future__ import annotations

import math
import re
from typing import Any

# Tuning knobs (documented in /methodology/skeleton).
TOPIC_SHIFT_DISTANCE = 0.70     # TF-IDF cosine distance threshold for a shift
                                # (calibrated on small-document corpora —
                                # WhisperX phrases produce high-variance
                                # distances, so we under-call rather than
                                # over-call shifts in v1; recalibrate via
                                # scripts/calibrate_skeleton.py once a real
                                # corpus accumulates)
ENERGY_SPIKE_STD = 2.5          # how many local-std above mean to count as a spike
SILENCE_RMS_FLOOR = 0.05        # below this is "silent enough"
SILENCE_MIN_SECONDS = 1.0       # silences shorter than this are noise
ALIGNMENT_WINDOW_SECONDS = 1.0  # cross-modal events within this are "aligned"


# ─── Text events: TF-IDF topic shifts ─────────────────────────────────────────

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _tf_vector(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counts: dict[str, int] = {}
    for tok in tokens:
        counts[tok] = counts.get(tok, 0) + 1
    n = float(len(tokens))
    return {tok: c / n for tok, c in counts.items()}


def _idf_vector(documents: list[list[str]]) -> dict[str, float]:
    """Smoothed IDF across a small list of documents (the segments).
    Standard formula: idf(t) = log((N + 1) / (df(t) + 1)) + 1.
    """
    df: dict[str, int] = {}
    for doc in documents:
        for tok in set(doc):
            df[tok] = df.get(tok, 0) + 1
    n = len(documents)
    return {tok: math.log((n + 1) / (count + 1)) + 1.0 for tok, count in df.items()}


def _tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = _tf_vector(tokens)
    return {tok: weight * idf.get(tok, 0.0) for tok, weight in tf.items()}


def _cosine_distance(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 1.0
    keys = set(a) | set(b)
    dot = 0.0
    na = 0.0
    nb = 0.0
    for k in keys:
        va = a.get(k, 0.0)
        vb = b.get(k, 0.0)
        dot += va * vb
        na += va * va
        nb += vb * vb
    denom = math.sqrt(na * nb)
    if denom <= 0:
        return 1.0
    sim = dot / denom
    return max(0.0, min(1.0, 1.0 - sim))


def _first_sentence(text: str, max_words: int = 14) -> str:
    """Return the first sentence (or first N words) of `text` so the user
    sees a real before/after sample at each topic shift — not an invented
    LLM summary."""
    text = (text or "").strip()
    if not text:
        return ""
    # Find first sentence terminator.
    m = re.search(r"[.!?](\s|$)", text)
    if m:
        candidate = text[: m.start() + 1]
        if len(candidate.split()) >= 3:
            return candidate.strip()
    # Otherwise truncate to max_words.
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


def detect_text_events(transcript_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect topic shifts as TF-IDF cosine-distance peaks between
    consecutive transcript segments. Each event carries the actual
    before/after sentence the user heard."""
    if not transcript_segments or len(transcript_segments) < 2:
        return []
    docs = [_tokenize(seg.get("text", "")) for seg in transcript_segments]
    idf = _idf_vector(docs)
    vectors = [_tfidf_vector(d, idf) for d in docs]
    events: list[dict[str, Any]] = []
    for i in range(1, len(vectors)):
        dist = _cosine_distance(vectors[i - 1], vectors[i])
        if dist >= TOPIC_SHIFT_DISTANCE:
            score = max(0.0, min(1.0, (dist - TOPIC_SHIFT_DISTANCE) / 0.45))
            events.append({
                "time": float(transcript_segments[i].get("start", 0.0) or 0.0),
                "type": "topic_shift",
                "score": round(score, 3),
                "distance": round(dist, 3),
                "before_summary": _first_sentence(transcript_segments[i - 1].get("text", "")),
                "after_summary": _first_sentence(transcript_segments[i].get("text", "")),
            })
    return events


# ─── Audio events: energy spikes + long silences ───────────────────────────────


def _local_mean_std(values: list[float], window: int = 8) -> list[tuple[float, float]]:
    """Rolling local mean + std around each index, used to detect spikes
    relative to the surrounding signal rather than against a global mean."""
    n = len(values)
    out: list[tuple[float, float]] = []
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        chunk = values[lo:hi]
        m = sum(chunk) / len(chunk)
        var = sum((x - m) ** 2 for x in chunk) / len(chunk)
        out.append((m, math.sqrt(max(var, 1e-9))))
    return out


def detect_audio_events(
    waveform: list[float],
    duration_seconds: float,
) -> list[dict[str, Any]]:
    """Energy spikes + long silences from a 200-bin RMS waveform."""
    if not waveform or duration_seconds <= 0:
        return []
    n = len(waveform)
    seconds_per_bin = duration_seconds / max(1, n)
    stats = _local_mean_std(waveform)
    events: list[dict[str, Any]] = []

    # Spikes (with non-maximum suppression so a single loud moment isn't
    # detected several times across adjacent bins).
    suppress_until_idx = -1
    nms_window = max(2, int(round(0.5 / max(1e-6, seconds_per_bin))))  # ~0.5s window
    for i, v in enumerate(waveform):
        if i <= suppress_until_idx:
            continue
        m, s = stats[i]
        z = (v - m) / s
        if z >= ENERGY_SPIKE_STD and v >= 0.10:
            time = round(i * seconds_per_bin, 2)
            score = max(0.0, min(1.0, (z - ENERGY_SPIKE_STD) / 3.0))
            events.append({
                "time": time,
                "type": "energy_spike",
                "score": round(score, 3),
                "rms": round(float(v), 4),
                "z": round(float(z), 2),
            })
            suppress_until_idx = i + nms_window

    # Long silences. Walk the bins, group runs of low-energy.
    if SILENCE_MIN_SECONDS > 0 and seconds_per_bin > 0:
        min_run_bins = max(1, int(round(SILENCE_MIN_SECONDS / seconds_per_bin)))
        i = 0
        while i < n:
            if waveform[i] < SILENCE_RMS_FLOOR:
                start = i
                while i < n and waveform[i] < SILENCE_RMS_FLOOR:
                    i += 1
                end = i  # exclusive
                if (end - start) >= min_run_bins:
                    events.append({
                        "time": round(start * seconds_per_bin, 2),
                        "type": "silence_start",
                        "score": round(min(1.0, (end - start) / (min_run_bins * 4)), 3),
                        "duration_seconds": round((end - start) * seconds_per_bin, 2),
                    })
            else:
                i += 1
    events.sort(key=lambda e: e["time"])
    return events


# ─── Visual events: scene cuts from keyframe timestamps ───────────────────────


def detect_visual_events(keyframes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each keyframe is a real scene-detected boundary (or a uniformly-
    sampled fallback when scdet returned fewer than expected — see
    backend/media_features.video_keyframes). Treat each keyframe time
    as a visual event."""
    if not keyframes:
        return []
    events: list[dict[str, Any]] = []
    for i, kf in enumerate(keyframes):
        time = float(kf.get("time", 0.0) or 0.0)
        # Magnitude proxy: closeness to the previous keyframe — denser
        # keyframes mean faster cutting cadence.
        prev_time = float(keyframes[i - 1].get("time", 0.0)) if i > 0 else 0.0
        gap = max(0.0, time - prev_time)
        magnitude = round(1.0 / max(1.0, gap), 3) if i > 0 else 0.5
        events.append({
            "time": round(time, 2),
            "type": "scene_cut" if i > 0 else "scene_open",
            "score": min(1.0, magnitude),
            "magnitude": magnitude,
        })
    return events


# ─── Cross-modal alignment ────────────────────────────────────────────────────


def compute_alignment(
    text_events: list[dict[str, Any]],
    visual_events: list[dict[str, Any]],
    audio_events: list[dict[str, Any]],
    *,
    window_seconds: float = ALIGNMENT_WINDOW_SECONDS,
) -> dict[str, Any]:
    """Bucket all events into a single timeline; mark a moment as 'aligned'
    if it has events from 2+ modalities within `window_seconds`. Misaligned
    moments are events with no companion in another modality within the
    window — the leading_modality field tells the user which lane fired
    first.

    cross_modal_alignment_score = aligned_events / total_events.
    """
    all_events: list[tuple[float, str]] = []
    for e in text_events:
        all_events.append((float(e["time"]), "text"))
    for e in visual_events:
        all_events.append((float(e["time"]), "visual"))
    for e in audio_events:
        all_events.append((float(e["time"]), "audio"))
    if not all_events:
        return {
            "cross_modal_alignment_score": 0.0,
            "aligned_moments": [],
            "misaligned_moments": [],
        }
    all_events.sort(key=lambda x: x[0])

    aligned_moments: list[dict[str, Any]] = []
    misaligned_moments: list[dict[str, Any]] = []
    aligned_count = 0
    used_indices: set[int] = set()

    for i, (t, modality) in enumerate(all_events):
        if i in used_indices:
            continue
        # Find any companion events from a *different* modality within window.
        companions: list[tuple[int, float, str]] = []
        for j in range(len(all_events)):
            if j == i:
                continue
            t2, m2 = all_events[j]
            if abs(t2 - t) <= window_seconds and m2 != modality:
                companions.append((j, t2, m2))
        if companions:
            modalities = {modality}
            for j, _t2, m2 in companions:
                modalities.add(m2)
                used_indices.add(j)
            used_indices.add(i)
            aligned_count += 1 + len(companions)
            aligned_moments.append({
                "time": round(t, 2),
                "modalities": sorted(modalities),
            })
        else:
            misaligned_moments.append({
                "time": round(t, 2),
                "leading_modality": modality,
                "lag_seconds": None,
            })

    score = round(aligned_count / max(1, len(all_events)), 3)
    return {
        "cross_modal_alignment_score": score,
        "aligned_moments": aligned_moments,
        "misaligned_moments": misaligned_moments,
    }


# ─── Public entry point ───────────────────────────────────────────────────────


def build_skeleton_for_side(
    transcript_segments: list[dict[str, Any]],
    waveform: list[float] | None,
    keyframes: list[dict[str, Any]] | None,
    *,
    duration_seconds: float | None,
) -> dict[str, Any]:
    """Build the full skeleton payload for one side (A or B)."""
    text_events = detect_text_events(transcript_segments or [])
    audio_events = (
        detect_audio_events(waveform, float(duration_seconds or 0.0))
        if waveform else []
    )
    visual_events = detect_visual_events(keyframes or [])
    alignment = compute_alignment(text_events, visual_events, audio_events)

    n_text = len(text_events)
    n_visual = len(visual_events)
    n_audio = len(audio_events)
    summary_line = (
        f"{n_text} topic shift{'s' if n_text != 1 else ''}"
        f" · {n_visual} scene cut{'s' if n_visual != 1 else ''}"
        f" · {n_audio} audio transition{'s' if n_audio != 1 else ''}"
        f" · alignment {alignment['cross_modal_alignment_score']:.2f}"
    )
    return {
        "text_events": text_events,
        "visual_events": visual_events,
        "audio_events": audio_events,
        "alignment": alignment,
        "summary_line": summary_line,
    }


def build_skeleton_both_sides(
    transcript_segments_a: list[dict[str, Any]] | None,
    transcript_segments_b: list[dict[str, Any]] | None,
    waveform_a: list[float] | None,
    waveform_b: list[float] | None,
    keyframes_a: list[dict[str, Any]] | None,
    keyframes_b: list[dict[str, Any]] | None,
    *,
    duration_a_s: float | None,
    duration_b_s: float | None,
) -> dict[str, Any]:
    """Build skeletons for A and B; the structural-similarity sketch
    compares the *sequence of event types* across both sides."""
    a = build_skeleton_for_side(
        transcript_segments_a, waveform_a, keyframes_a, duration_seconds=duration_a_s,
    )
    b = build_skeleton_for_side(
        transcript_segments_b, waveform_b, keyframes_b, duration_seconds=duration_b_s,
    )
    # Structural similarity: cosine of the (event-type) bag-of-counts vectors.
    def _counts(side: dict[str, Any]) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in side.get("text_events", []):
            out["text:" + e.get("type", "topic_shift")] = out.get("text:" + e.get("type", "topic_shift"), 0) + 1
        for e in side.get("visual_events", []):
            out["visual:" + e.get("type", "scene_cut")] = out.get("visual:" + e.get("type", "scene_cut"), 0) + 1
        for e in side.get("audio_events", []):
            out["audio:" + e.get("type", "energy_spike")] = out.get("audio:" + e.get("type", "energy_spike"), 0) + 1
        return out
    ca = _counts(a)
    cb = _counts(b)
    keys = set(ca) | set(cb)
    if not keys:
        struct_sim = 1.0
    else:
        dot = sum(ca.get(k, 0) * cb.get(k, 0) for k in keys)
        na = math.sqrt(sum(v * v for v in ca.values()))
        nb = math.sqrt(sum(v * v for v in cb.values()))
        struct_sim = round(dot / (na * nb), 3) if na > 0 and nb > 0 else 0.0
    return {"a": a, "b": b, "structural_similarity": struct_sim}
