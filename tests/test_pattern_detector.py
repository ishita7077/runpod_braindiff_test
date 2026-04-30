"""Synthetic unit tests for backend/pattern_detector.py.

We hand-craft per-dimension timeseries designed to:
  - trigger a single pattern cleanly,
  - co-trigger two overlapping patterns,
  - get filtered out by the min_duration_seconds rule,
  - stay below threshold when only one of the contributing dims is high,
  - degrade gracefully when timeseries are missing entirely.

These exercise the deterministic logic of the detector without needing
real model output — the whole point of pattern_detector is that it's
free of ML, so synthetic tests are the right tests.
"""
from __future__ import annotations

import pytest

from backend.pattern_detector import (
    detect_patterns_for_side,
    detect_patterns_both_sides,
    get_definitions,
)


def _dim_row(key: str, ts_a: list[float], ts_b: list[float]) -> dict:
    return {
        "key": key,
        "label": key.replace("_", " ").title(),
        "region": "test",
        "timeseries_a": ts_a,
        "timeseries_b": ts_b,
    }


def _seven_dims_zero(timesteps: int = 30) -> list[dict]:
    """Helper: 7-dimension scaffold all at 0.0 on both sides."""
    keys = [
        "personal_resonance",
        "social_thinking",
        "brain_effort",
        "language_depth",
        "gut_reaction",
        "memory_encoding",
        "attention_salience",
    ]
    zeros = [0.0] * timesteps
    return [_dim_row(k, list(zeros), list(zeros)) for k in keys]


def _set_dim(rows: list[dict], key: str, side: str, values: list[float]) -> None:
    for r in rows:
        if r["key"] == key:
            r[f"timeseries_{side}"] = values
            return


def test_definitions_load_and_have_v1_patterns():
    defs = get_definitions()
    pids = [p["id"] for p in defs.get("patterns", [])]
    # All four shipped v1 patterns must be present (Visceral Hit dropped).
    assert "learning_moment" in pids
    assert "emotional_impact" in pids
    assert "reasoning_beat" in pids
    assert "social_resonance" in pids
    assert "visceral_hit" not in pids


def test_clean_learning_moment_triggers():
    """Sustained high attention + memory = one Learning Moment block."""
    rows = _seven_dims_zero(timesteps=12)
    _set_dim(rows, "attention_salience", "a", [0.8] * 12)
    _set_dim(rows, "memory_encoding",    "a", [0.7] * 12)
    instances = detect_patterns_for_side(rows, "a", duration_seconds=12.0)
    learning = [i for i in instances if i["pattern_id"] == "learning_moment"]
    assert len(learning) == 1, instances
    inst = learning[0]
    assert inst["start_seconds"] <= 1.0
    assert inst["end_seconds"] >= 11.0


def test_overlapping_patterns_can_coexist():
    """A second can belong to multiple patterns. Reasoning Beat + Learning
    Moment can fire on the same window — detector must surface both."""
    rows = _seven_dims_zero(timesteps=10)
    # Active dims for both Reasoning Beat (effort + language) and Learning
    # Moment (attention + memory). They overlap in time.
    _set_dim(rows, "attention_salience", "b", [0.7] * 10)
    _set_dim(rows, "memory_encoding",    "b", [0.7] * 10)
    _set_dim(rows, "brain_effort",       "b", [0.6] * 10)
    _set_dim(rows, "language_depth",     "b", [0.6] * 10)
    instances = detect_patterns_for_side(rows, "b", duration_seconds=10.0)
    pids = {i["pattern_id"] for i in instances}
    assert "learning_moment" in pids
    assert "reasoning_beat" in pids


def test_short_block_filtered_by_min_duration():
    """A 1-step blip in attention+memory should NOT trigger Learning
    Moment because min_duration_seconds = 2."""
    rows = _seven_dims_zero(timesteps=20)
    spikes_a = [0.0] * 20
    spikes_a[5] = 0.9  # single timestep above threshold
    spikes_m = [0.0] * 20
    spikes_m[5] = 0.9
    _set_dim(rows, "attention_salience", "a", spikes_a)
    _set_dim(rows, "memory_encoding",    "a", spikes_m)
    instances = detect_patterns_for_side(rows, "a", duration_seconds=20.0)
    learning = [i for i in instances if i["pattern_id"] == "learning_moment"]
    assert learning == [], "single-step blips must be filtered by min_duration_seconds"


def test_one_dim_high_does_not_trigger_and_high():
    """Learning Moment requires BOTH attention AND memory above threshold.
    High attention with low memory must NOT trigger."""
    rows = _seven_dims_zero(timesteps=10)
    _set_dim(rows, "attention_salience", "a", [0.9] * 10)
    _set_dim(rows, "memory_encoding",    "a", [0.10] * 10)
    instances = detect_patterns_for_side(rows, "a", duration_seconds=10.0)
    learning = [i for i in instances if i["pattern_id"] == "learning_moment"]
    assert learning == []


def test_emotional_impact_triggers_independently():
    rows = _seven_dims_zero(timesteps=10)
    _set_dim(rows, "personal_resonance", "a", [0.7] * 10)
    _set_dim(rows, "gut_reaction",       "a", [0.7] * 10)
    instances = detect_patterns_for_side(rows, "a", duration_seconds=10.0)
    pids = {i["pattern_id"] for i in instances}
    assert pids == {"emotional_impact"}, pids


def test_social_resonance_triggers_independently():
    rows = _seven_dims_zero(timesteps=10)
    _set_dim(rows, "social_thinking",    "b", [0.7] * 10)
    _set_dim(rows, "personal_resonance", "b", [0.7] * 10)
    instances = detect_patterns_for_side(rows, "b", duration_seconds=10.0)
    pids = {i["pattern_id"] for i in instances}
    assert pids == {"social_resonance"}, pids


def test_no_patterns_when_all_dims_below_threshold():
    rows = _seven_dims_zero(timesteps=20)
    instances = detect_patterns_for_side(rows, "a", duration_seconds=20.0)
    assert instances == []


def test_degrades_gracefully_with_empty_dimension_rows():
    instances = detect_patterns_for_side([], "a")
    assert instances == []


def test_both_sides_helper():
    rows = _seven_dims_zero(timesteps=10)
    _set_dim(rows, "attention_salience", "a", [0.7] * 10)
    _set_dim(rows, "memory_encoding",    "a", [0.7] * 10)
    _set_dim(rows, "personal_resonance", "b", [0.7] * 10)
    _set_dim(rows, "gut_reaction",       "b", [0.7] * 10)
    out = detect_patterns_both_sides(rows, duration_a_s=10.0, duration_b_s=10.0)
    a_pids = {i["pattern_id"] for i in out["a"]}
    b_pids = {i["pattern_id"] for i in out["b"]}
    assert "learning_moment" in a_pids
    assert "emotional_impact" in b_pids


def test_peak_seconds_within_block():
    rows = _seven_dims_zero(timesteps=10)
    # Peak attention at t=4, memory peaks around t=5.
    att = [0.6, 0.7, 0.8, 0.85, 0.95, 0.85, 0.75, 0.65, 0.6, 0.55]
    mem = [0.5, 0.6, 0.65, 0.7, 0.85, 0.95, 0.8, 0.65, 0.55, 0.5]
    _set_dim(rows, "attention_salience", "a", att)
    _set_dim(rows, "memory_encoding",    "a", mem)
    [inst] = [i for i in detect_patterns_for_side(rows, "a", duration_seconds=10.0)
              if i["pattern_id"] == "learning_moment"]
    # Peak should be inside the active block.
    assert inst["start_seconds"] <= inst["peak_seconds"] <= inst["end_seconds"]
    # Peak intensity should reflect the mean of contributing dims at peak.
    assert 0.7 < inst["peak_intensity"] <= 1.0


def test_contributing_dim_values_present():
    rows = _seven_dims_zero(timesteps=8)
    _set_dim(rows, "brain_effort",       "a", [0.6] * 8)
    _set_dim(rows, "language_depth",     "a", [0.6] * 8)
    [inst] = [i for i in detect_patterns_for_side(rows, "a", duration_seconds=8.0)
              if i["pattern_id"] == "reasoning_beat"]
    cdv = inst["contributing_dim_values"]
    assert "brain_effort" in cdv
    assert "language_depth" in cdv
    assert all(abs(v - 0.6) < 1e-6 for v in cdv["brain_effort"])
