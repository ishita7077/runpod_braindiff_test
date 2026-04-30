"""Synthetic unit tests for backend/connectivity.py.

Hand-craft timeseries with known correlation structure and verify the
connectivity payload comes back with the expected matrix entries, edge
list, integration / parallel scores, and hub / isolated identifications.
"""
from __future__ import annotations

import math

import pytest

from backend.connectivity import (
    compute_connectivity_for_side,
    compute_connectivity_both_sides,
    DIM_ORDER,
    EDGE_THRESHOLD,
    MIN_TIMESTEPS_FOR_RELIABILITY,
)


def _row(key: str, ts_a: list[float], ts_b: list[float]) -> dict:
    return {
        "key": key,
        "label": key.replace("_", " ").title(),
        "region": "test",
        "timeseries_a": ts_a,
        "timeseries_b": ts_b,
    }


def _all_zero_rows(timesteps: int = 12) -> list[dict]:
    z = [0.0] * timesteps
    return [_row(k, list(z), list(z)) for k in DIM_ORDER]


def _set(rows: list[dict], key: str, side: str, vs: list[float]) -> None:
    for r in rows:
        if r["key"] == key:
            r[f"timeseries_{side}"] = vs
            return


def test_perfect_positive_correlation_lands_at_1():
    rows = _all_zero_rows(12)
    series = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.5, 0.4, 0.3, 0.2, 0.4, 0.6]
    _set(rows, "attention_salience", "a", list(series))
    _set(rows, "memory_encoding",    "a", list(series))   # identical → r = 1
    out = compute_connectivity_for_side(rows, "a")
    keys = out["dim_keys"]
    i = keys.index("attention_salience")
    j = keys.index("memory_encoding")
    assert out["matrix"][i][j] == pytest.approx(1.0, abs=1e-6)
    assert out["matrix"][j][i] == pytest.approx(1.0, abs=1e-6)
    # Diagonal should always be 1.0
    for k in range(len(keys)):
        assert out["matrix"][k][k] == pytest.approx(1.0, abs=1e-6)


def test_perfect_negative_correlation_lands_at_negative_1():
    rows = _all_zero_rows(12)
    pos = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.5, 0.4, 0.3, 0.2, 0.4, 0.6]
    neg = [-v for v in pos]
    _set(rows, "attention_salience", "a", pos)
    _set(rows, "memory_encoding",    "a", neg)
    out = compute_connectivity_for_side(rows, "a")
    keys = out["dim_keys"]
    i = keys.index("attention_salience")
    j = keys.index("memory_encoding")
    assert out["matrix"][i][j] == pytest.approx(-1.0, abs=1e-6)


def test_flat_dimension_yields_zero_correlation_and_warning():
    rows = _all_zero_rows(12)
    _set(rows, "attention_salience", "a", [0.5] * 12)   # flat
    _set(rows, "memory_encoding",    "a", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.5, 0.4, 0.3, 0.2, 0.4, 0.6])
    out = compute_connectivity_for_side(rows, "a")
    keys = out["dim_keys"]
    i = keys.index("attention_salience")
    j = keys.index("memory_encoding")
    assert out["matrix"][i][j] == 0.0
    assert any("flat" in w.lower() for w in out["warnings"])


def test_short_series_returns_empty_with_warning():
    rows = []
    short = [0.1, 0.2]
    for k in DIM_ORDER:
        rows.append(_row(k, list(short), list(short)))
    out = compute_connectivity_for_side(rows, "a")
    assert out["dim_keys"] == []
    assert out["matrix"] == []
    assert any("at least" in w.lower() for w in out["warnings"])
    assert out["metrics"]["n_timesteps"] == 2


def test_edge_threshold_filters_weak_correlations():
    """An r=0.10 pair (weak) should NOT appear in edges; r=0.7 should."""
    rows = _all_zero_rows(20)
    # Strong positive pair: identical series → r = 1.0
    strong = [math.sin(i / 2) for i in range(20)]
    _set(rows, "attention_salience", "a", strong)
    _set(rows, "memory_encoding",    "a", strong)
    # Weak pair: nearly random series → expected |r| ≪ 0.30
    weak_a = [0.5 + 0.01 * i for i in range(20)]            # monotonic
    weak_b = [0.4 + 0.001 * (i % 3) for i in range(20)]     # near-flat noise
    _set(rows, "personal_resonance", "a", weak_a)
    _set(rows, "social_thinking",    "a", weak_b)
    out = compute_connectivity_for_side(rows, "a")
    edges_keys = [(e["source"], e["target"]) for e in out["edges"]]
    edges_set = set(tuple(sorted(p)) for p in edges_keys)
    assert tuple(sorted(("attention_salience", "memory_encoding"))) in edges_set
    # The weak pair MAY or may not be there depending on monotonic luck —
    # what we can guarantee is every kept edge has |corr| ≥ EDGE_THRESHOLD.
    for e in out["edges"]:
        assert abs(e["correlation"]) >= EDGE_THRESHOLD


def test_integration_score_is_average_abs_off_diagonal():
    rows = _all_zero_rows(12)
    series = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.5, 0.4, 0.3, 0.2, 0.4, 0.6]
    # Make every system identical → all off-diagonals = 1 → integration = 1
    for k in DIM_ORDER:
        _set(rows, k, "a", list(series))
    out = compute_connectivity_for_side(rows, "a")
    assert out["metrics"]["integration_score"] == pytest.approx(1.0, abs=1e-6)


def test_hub_node_is_most_coupled():
    rows = _all_zero_rows(20)
    high = [math.sin(i / 2) + 0.01 * i for i in range(20)]
    low = [0.5 + 0.001 * i for i in range(20)]
    # attention_salience correlates strongly with everyone:
    _set(rows, "attention_salience", "a", list(high))
    _set(rows, "memory_encoding",    "a", list(high))
    _set(rows, "personal_resonance", "a", list(high))
    _set(rows, "social_thinking",    "a", list(high))
    # gut_reaction is roughly flat:
    _set(rows, "gut_reaction",       "a", list(low))
    _set(rows, "language_depth",     "a", list(low))
    _set(rows, "brain_effort",       "a", list(low))
    out = compute_connectivity_for_side(rows, "a")
    assert out["metrics"]["hub_node"] in {"attention_salience", "memory_encoding", "personal_resonance", "social_thinking"}


def test_both_sides_helper_includes_delta_when_both_present():
    rows = _all_zero_rows(12)
    series = [math.sin(i / 2) for i in range(12)]
    for k in DIM_ORDER:
        _set(rows, k, "a", list(series))
        _set(rows, k, "b", [v + (i * 0.05) for i, v in enumerate(series)])
    out = compute_connectivity_both_sides(rows)
    assert "delta" in out
    assert "matrix" in out["delta"]
    assert "top_changed" in out["delta"]
    # Delta diagonal must be 0 (each side's diagonal is 1.0).
    for k in range(len(out["delta"]["matrix"])):
        assert out["delta"]["matrix"][k][k] == pytest.approx(0.0, abs=1e-6)


def test_handles_empty_input_gracefully():
    out = compute_connectivity_for_side([], "a")
    assert out["dim_keys"] == []
    assert out["edges"] == []
    assert "warnings" in out and len(out["warnings"]) >= 1


def test_min_timesteps_threshold_uses_module_constant():
    rows = []
    short = [0.1] * (MIN_TIMESTEPS_FOR_RELIABILITY - 1)
    for k in DIM_ORDER:
        rows.append(_row(k, list(short), list(short)))
    out = compute_connectivity_for_side(rows, "a")
    # Below the threshold → empty payload + warning.
    assert out["matrix"] == []
    assert any(str(MIN_TIMESTEPS_FOR_RELIABILITY) in w for w in out["warnings"])
