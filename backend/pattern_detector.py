"""Co-activation pattern detection for the Brain Diff results pages.

Reads pattern definitions from `frontend_new/data/pattern-definitions.json`
(single source of truth — same file the frontend reads), evaluates each
pattern against the per-dimension timeseries the worker already returns,
and emits pattern instances with start/end seconds, peak time, and the
contributing per-dimension values during the matching window.

Design notes:

- Deterministic. No ML, no fitting. Given the same timeseries + the same
  thresholds, you get the same pattern instances.

- Coalesces contiguous "active" timesteps into blocks. Filters blocks
  shorter than `min_duration_seconds`. A second can belong to multiple
  patterns at once — that is intentional (Learning Moment + Reasoning
  Beat can co-occur).

- Conservative thresholds (60–70th percentile defaults). The pattern
  definitions JSON documents this and points at scripts/calibrate_patterns.py
  which we ship for re-deriving thresholds against any future corpus.

- All pattern logic is `AND_HIGH` (all listed dims simultaneously above
  threshold) in v1. The schema also accepts `INVERSE` (one above, another
  below) — kept on the schema for future patterns even though we shipped
  v1 with no inverse patterns (Visceral Hit was dropped as scientifically
  shaky in the verification pass).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("braindiff.pattern_detector")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PATTERN_DEFS_PATH = _REPO_ROOT / "frontend_new" / "data" / "pattern-definitions.json"


def _load_definitions() -> dict[str, Any]:
    """Read the JSON once and cache. Falls back to an empty pattern set
    if the file is missing — never raises, never blocks job completion."""
    try:
        with open(_PATTERN_DEFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("pattern_detector: definitions file not found at %s", _PATTERN_DEFS_PATH)
        return {"patterns": []}
    except json.JSONDecodeError as err:
        logger.warning("pattern_detector: definitions JSON is malformed: %s", err)
        return {"patterns": []}


_CACHED_DEFS: dict[str, Any] | None = None


def get_definitions() -> dict[str, Any]:
    global _CACHED_DEFS
    if _CACHED_DEFS is None:
        _CACHED_DEFS = _load_definitions()
    return _CACHED_DEFS


def _normalised_timeseries(rows: list[dict[str, Any]], side: str) -> dict[str, list[float]]:
    """Pull `timeseries_a` or `timeseries_b` out of the dimension rows
    we already include in the result and key them by `dim.key` so the
    pattern logic can look them up by id."""
    field = "timeseries_a" if side == "a" else "timeseries_b"
    out: dict[str, list[float]] = {}
    for row in rows:
        key = row.get("key")
        if not key:
            continue
        ts = row.get(field) or []
        if not isinstance(ts, list):
            continue
        out[key] = [float(v) for v in ts if v is not None]
    return out


def _evaluate_at(pattern: dict[str, Any], series: dict[str, list[float]], t: int) -> bool:
    logic = pattern.get("logic", "AND_HIGH")
    thresholds = pattern.get("thresholds", {}) or {}
    dims = pattern.get("dims", []) or []
    if logic == "AND_HIGH":
        for dim_id in dims:
            ts = series.get(dim_id)
            if ts is None or t >= len(ts):
                return False
            if ts[t] < thresholds.get(dim_id, 0.5):
                return False
        return True
    if logic == "INVERSE":
        # Schema-level support for future patterns: one dim ≥ its threshold
        # while another is ≤ its threshold. v1 ships zero INVERSE patterns
        # (Visceral Hit was dropped). Keeping the branch so adding one later
        # is a JSON change, not a code change.
        directions = pattern.get("directions") or {}
        for dim_id in dims:
            ts = series.get(dim_id)
            if ts is None or t >= len(ts):
                return False
            value = ts[t]
            direction = directions.get(dim_id, "high")
            threshold = thresholds.get(dim_id, 0.5)
            if direction == "high" and value < threshold:
                return False
            if direction == "low" and value > threshold:
                return False
        return True
    return False


def _coalesce_blocks(active: list[bool], min_duration: int) -> list[tuple[int, int]]:
    """Return [(start_idx_inclusive, end_idx_inclusive), …] for runs of True
    at least `min_duration` long. Indices are timesteps; the caller maps
    them to seconds using the run's duration."""
    blocks: list[tuple[int, int]] = []
    i = 0
    n = len(active)
    while i < n:
        if not active[i]:
            i += 1
            continue
        start = i
        while i < n and active[i]:
            i += 1
        end = i - 1
        if (end - start + 1) >= min_duration:
            blocks.append((start, end))
    return blocks


def _peak_within(
    block: tuple[int, int],
    series: dict[str, list[float]],
    dims: list[str],
) -> tuple[int, float]:
    """Return (peak_timestep_within_block, peak_intensity).

    Peak intensity = mean of the contributing dim values at that timestep.
    Useful for the frontend Pattern Card "biggest beat in this block" label.
    """
    start, end = block
    best_t = start
    best_score = -1.0
    for t in range(start, end + 1):
        scores = []
        for dim_id in dims:
            ts = series.get(dim_id)
            if ts is None or t >= len(ts):
                continue
            scores.append(ts[t])
        if not scores:
            continue
        score = sum(scores) / len(scores)
        if score > best_score:
            best_score = score
            best_t = t
    return best_t, best_score if best_score >= 0 else 0.0


def _timestep_to_seconds(t: int, total_steps: int, duration_seconds: float) -> float:
    if total_steps <= 1 or duration_seconds <= 0:
        return float(t)
    return float(round(duration_seconds * (t / max(total_steps - 1, 1)), 2))


def detect_patterns_for_side(
    dimension_rows: list[dict[str, Any]],
    side: str,
    *,
    duration_seconds: float | None = None,
    definitions: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Detect every pattern instance on Version A or B of one job.

    Returns a list of {pattern_id, name, start_seconds, end_seconds,
    peak_seconds, peak_intensity, contributing_dim_values, timestep_range}
    — designed to be embedded directly into result.meta.media_features.
    """
    defs = definitions or get_definitions()
    patterns = defs.get("patterns") or []
    series = _normalised_timeseries(dimension_rows, side)
    if not series:
        return []
    total_steps = max((len(v) for v in series.values()), default=0)
    if total_steps == 0:
        return []

    out: list[dict[str, Any]] = []
    for pattern in patterns:
        pid = pattern.get("id")
        if not pid:
            continue
        active = [_evaluate_at(pattern, series, t) for t in range(total_steps)]
        min_steps = max(1, int(pattern.get("min_duration_seconds") or 1))
        # min_duration is in *seconds*; convert to timesteps using the
        # duration anchor when one is provided, else treat 1 timestep ≈ 1 s.
        if duration_seconds and duration_seconds > 0:
            steps_per_second = total_steps / duration_seconds
            min_steps = max(1, int(round(min_steps * steps_per_second / 1.0)))
        blocks = _coalesce_blocks(active, min_steps)
        for block in blocks:
            start, end = block
            peak_t, peak_intensity = _peak_within(block, series, pattern.get("dims") or [])
            contributing = {
                dim_id: [
                    round(series.get(dim_id, [0.0])[i], 4)
                    for i in range(start, end + 1)
                    if i < len(series.get(dim_id, []))
                ]
                for dim_id in (pattern.get("dims") or [])
            }
            out.append({
                "pattern_id": pid,
                "name": pattern.get("name") or pid,
                "start_seconds": _timestep_to_seconds(start, total_steps, duration_seconds or float(total_steps)),
                "end_seconds": _timestep_to_seconds(end, total_steps, duration_seconds or float(total_steps)),
                "peak_seconds": _timestep_to_seconds(peak_t, total_steps, duration_seconds or float(total_steps)),
                "peak_intensity": round(float(peak_intensity), 4),
                "contributing_dim_values": contributing,
                "timestep_range": [int(start), int(end)],
                "total_timesteps": int(total_steps),
            })
    out.sort(key=lambda p: p["start_seconds"])
    return out


def detect_patterns_both_sides(
    dimension_rows: list[dict[str, Any]],
    *,
    duration_a_s: float | None = None,
    duration_b_s: float | None = None,
    definitions: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Convenience: detect for both A and B in one call. Used by the
    worker + local FastAPI when assembling the result payload."""
    return {
        "a": detect_patterns_for_side(dimension_rows, "a", duration_seconds=duration_a_s, definitions=definitions),
        "b": detect_patterns_for_side(dimension_rows, "b", duration_seconds=duration_b_s, definitions=definitions),
    }
