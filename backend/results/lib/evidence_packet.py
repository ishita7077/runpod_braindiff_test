"""Evidence packet builder — Phase C.2 of the production fix plan.

The evidence packet is a compact, structured summary of a comparison that the
LLM can reason over without drowning in raw timeseries. It feeds the
analysis_brief slot (Phase C.3) which then feeds every section writer.

Why this matters: Gemma 3 1B has a small attention budget. When you dump 60
seconds × 7 systems = 420 floats per video at it, the model spends its
budget summarising the data instead of reasoning about it. The packet does
the summary deterministically, so the model only sees the salient facts.

What's in the packet:
  * videos: id, display_name, duration, hub_node, integration_score
  * top_deltas:    the 3 systems with the largest A-vs-B mean delta
  * top_moments:   per video, the strongest peak time + value per system
  * couplings:     strongest, weakest, anti-coupling per video
  * chords:        every chord event with timestamp + quote
  * transcript_quotes: timestamped lines from each video, deduped + length-capped
  * media_structure: simple stats (segment counts, avg gap, total speech time)

Every field is deterministic. The LLM is responsible only for choosing which
of these facts to LEAD with, and how to phrase them. No fact in the final
content should be unreachable from this packet.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .input_normalizer import CANONICAL_SYSTEMS, NormalizedInputs, VideoSignature


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

_SYSTEM_DISPLAY: dict[str, str] = {
    "personal_resonance": "Self-relevance",
    "attention":          "Attention",
    "brain_effort":       "Cognitive control",
    "gut_reaction":       "Visceral response",
    "memory_encoding":    "Memory encoding",
    "social_thinking":    "Theory-of-mind",
    "language_depth":     "Language",
}


def _format_timestamp(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


def _video_id_to_evidence_prefix(video: VideoSignature, video_key: str) -> str:
    return video_key  # consistent prefix the LLM can echo back


def _quote_ref(video_key: str, seconds: float) -> str:
    return f"{video_key}:{_format_timestamp(seconds)}"


# ────────────────────────────────────────────────────────────
# Section builders
# ────────────────────────────────────────────────────────────

def _video_summary(video: VideoSignature) -> dict[str, Any]:
    return {
        "id": video.id,
        "display_name": video.display_name,
        "duration_seconds": float(video.duration_seconds),
        "hub_node": video.hub_node,
        "integration_score": float(video.integration_score),
        "system_means": {k: float(v) for k, v in video.system_means.items()},
    }


def _top_deltas(va: VideoSignature, vb: VideoSignature, *, n: int = 3) -> list[dict[str, Any]]:
    """Per-system mean delta (A − B), sorted by absolute magnitude."""
    deltas: list[dict[str, Any]] = []
    for system in CANONICAL_SYSTEMS:
        ma = float(va.system_means.get(system, 0.0))
        mb = float(vb.system_means.get(system, 0.0))
        deltas.append({
            "system": system,
            "system_display": _SYSTEM_DISPLAY.get(system, system),
            "video_a_mean": ma,
            "video_b_mean": mb,
            "delta_a_minus_b": ma - mb,
            "abs_delta": abs(ma - mb),
        })
    deltas.sort(key=lambda d: d["abs_delta"], reverse=True)
    return deltas[:n]


def _top_moments(video: VideoSignature, video_key: str, *, per_system: int = 1) -> list[dict[str, Any]]:
    """For each canonical system, the strongest peak: (system, t, value, evidence_ref)."""
    out: list[dict[str, Any]] = []
    peaks = video.system_peaks or {}
    for system in CANONICAL_SYSTEMS:
        peak = peaks.get(system)
        if not peak:
            continue
        t = float(peak.get("time", 0.0))
        v = float(peak.get("value", 0.0))
        out.append({
            "video": video_key,
            "system": system,
            "system_display": _SYSTEM_DISPLAY.get(system, system),
            "time_seconds": t,
            "time_display": _format_timestamp(t),
            "value": v,
            "evidence_ref": _quote_ref(video_key, t),
        })
    # Sort by value descending so the LLM sees the strongest first.
    out.sort(key=lambda m: m["value"], reverse=True)
    return out[: per_system * len(CANONICAL_SYSTEMS)]


def _coupling_extremes(video: VideoSignature, video_key: str) -> list[dict[str, Any]]:
    """Strongest +, weakest abs, and most negative coupling per video."""
    couplings = list(video.couplings or [])
    if not couplings:
        return []
    by_r = sorted(couplings, key=lambda c: c.r, reverse=True)
    by_abs = sorted(couplings, key=lambda c: abs(c.r), reverse=True)
    by_abs_min = sorted(couplings, key=lambda c: abs(c.r))
    most_neg = sorted(couplings, key=lambda c: c.r)[0]
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _push(kind: str, c: Any) -> None:
        key = (kind, c.system_a, c.system_b)
        if key in seen:
            return
        seen.add(key)
        out.append({
            "video": video_key,
            "kind": kind,
            "system_a": c.system_a,
            "system_a_display": _SYSTEM_DISPLAY.get(c.system_a, c.system_a),
            "system_b": c.system_b,
            "system_b_display": _SYSTEM_DISPLAY.get(c.system_b, c.system_b),
            "r": float(c.r),
        })

    _push("strongest_positive", by_r[0])
    _push("weakest_absolute", by_abs_min[0])
    if most_neg.r < 0:
        _push("most_negative", most_neg)
    # Always include the strongest absolute (which may equal strongest_positive
    # — _push de-duplicates).
    _push("strongest_absolute", by_abs[0])
    return out


def _chord_events(video: VideoSignature, video_key: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in video.chord_events:
        out.append({
            "video": video_key,
            "chord_id": ev.chord_id,
            "time_seconds": float(ev.timestamp_seconds),
            "time_display": _format_timestamp(ev.timestamp_seconds),
            "duration_seconds": float(ev.duration_seconds),
            "evidence_ref": _quote_ref(video_key, ev.timestamp_seconds),
            "quote": ev.quote,
            "formula_values": dict(ev.formula_values or {}),
        })
    out.sort(key=lambda e: e["time_seconds"])
    return out


def _transcript_quotes(
    video: VideoSignature,
    video_key: str,
    *,
    max_quotes: int = 6,
    max_chars: int = 140,
) -> list[dict[str, Any]]:
    """Pick a small representative set of transcript lines.

    Strategy: take the first line, the last line, and lines closest to each
    chord event. Cap the total. Each quote carries its evidence_ref so the
    LLM can cite it directly (e.g. "video_a:0:08").
    """
    lines = list(video.transcript or [])
    if not lines:
        return []

    chosen_idx: list[int] = []
    if lines:
        chosen_idx.append(0)
    if len(lines) > 1:
        chosen_idx.append(len(lines) - 1)
    # Anchor a couple of lines near chord events.
    for ev in video.chord_events[:max_quotes]:
        # Pick the line whose start time is closest to the chord time.
        best_i = min(
            range(len(lines)),
            key=lambda i: abs(lines[i].t - ev.timestamp_seconds),
        )
        chosen_idx.append(best_i)
    # Dedupe + bound.
    seen: set[int] = set()
    final_idx: list[int] = []
    for i in chosen_idx:
        if i in seen:
            continue
        seen.add(i)
        final_idx.append(i)
        if len(final_idx) >= max_quotes:
            break
    # Sort chronologically.
    final_idx.sort()

    out: list[dict[str, Any]] = []
    for i in final_idx:
        ln = lines[i]
        text = (ln.text or "").strip()
        if len(text) > max_chars:
            text = text[: max_chars - 1].rstrip() + "…"
        if not text:
            continue
        out.append({
            "video": video_key,
            "time_seconds": float(ln.t),
            "time_display": _format_timestamp(ln.t),
            "evidence_ref": _quote_ref(video_key, ln.t),
            "text": text,
        })
    return out


def _media_structure(video: VideoSignature) -> dict[str, Any]:
    lines = list(video.transcript or [])
    if not lines:
        return {"segment_count": 0}
    # Approximate speech time as last_t - first_t (no end times in TranscriptLine).
    first = lines[0].t
    last = lines[-1].t
    return {
        "segment_count": len(lines),
        "first_segment_time_seconds": float(first),
        "last_segment_time_seconds": float(last),
        "spread_seconds": float(max(0.0, last - first)),
    }


# ────────────────────────────────────────────────────────────
# Top-level packet builder
# ────────────────────────────────────────────────────────────

def build_evidence_packet(inputs: NormalizedInputs) -> dict[str, Any]:
    """Assemble the deterministic evidence packet from a NormalizedInputs.

    Output is a JSON-safe dict with no numpy/dataclass instances. The LLM
    sees this verbatim (after json.dumps) inside the analysis_brief prompt.
    """
    va = inputs.video_a
    vb = inputs.video_b

    return {
        "schema_version": "evidence_packet.v1",
        "videos": {
            "video_a": _video_summary(va),
            "video_b": _video_summary(vb),
        },
        "top_deltas": _top_deltas(va, vb, n=3),
        "top_moments": _top_moments(va, "video_a") + _top_moments(vb, "video_b"),
        "couplings": _coupling_extremes(va, "video_a") + _coupling_extremes(vb, "video_b"),
        "chords": _chord_events(va, "video_a") + _chord_events(vb, "video_b"),
        "transcript_quotes": (
            _transcript_quotes(va, "video_a")
            + _transcript_quotes(vb, "video_b")
        ),
        "media_structure": {
            "video_a": _media_structure(va),
            "video_b": _media_structure(vb),
        },
    }


# ────────────────────────────────────────────────────────────
# Evidence-ref lookup — used by Phase C.6 to validate grounding
# ────────────────────────────────────────────────────────────

def collect_valid_evidence_refs(packet: dict[str, Any]) -> set[str]:
    """Return the set of evidence_refs actually present in the packet.

    A model recommendation that cites `video_b:0:14` is grounded only if
    that ref exists in our packet. The grounding validator (Phase C.6) runs
    every cited ref through this set.
    """
    refs: set[str] = set()
    for moment in packet.get("top_moments") or []:
        ref = moment.get("evidence_ref")
        if ref:
            refs.add(ref)
    for ev in packet.get("chords") or []:
        ref = ev.get("evidence_ref")
        if ref:
            refs.add(ref)
    for q in packet.get("transcript_quotes") or []:
        ref = q.get("evidence_ref")
        if ref:
            refs.add(ref)
    return refs
