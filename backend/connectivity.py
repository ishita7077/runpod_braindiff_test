"""Connectivity Map — pairwise correlation between cortical-system timeseries.

What this measures: for each pair of the 7 cortical systems (attention,
memory encoding, personal resonance, gut reaction, social thinking,
language depth, brain effort), how correlated are their per-second
predicted activations across the full run? A high positive correlation
means the two systems engaged together. A negative correlation means
they engaged in opposition (parallel processing). Near zero = independent.

This is the same family of metric used in clinical functional-connectivity
analysis (Power et al. 2011 "Functional network organization of the human
brain"; Sporns 2013, Curr Opin Neurobiol "Network attributes for
segregation and integration in the human brain"). The crucial caveat:
we compute correlation on TRIBE v2's predicted per-system activations,
NOT on raw fMRI. It's still informative — predicted timeseries inherit
the structure of the encoder + the training corpus — but it is not a
direct measurement of any individual's brain.

Output shape (matches /api/connectivity_map and meta.media_features.connectivity):
{
  "dim_keys": [list of 7 dim ids in stable display order],
  "labels":   [list of 7 human labels],
  "regions":  [list of 7 anatomical labels],
  "matrix":   [[7x7 floats, symmetric, diagonal = 1.0]],
  "edges":    [{source: dim, target: dim, weight: float, type: 'positive' | 'negative'}],
  "metrics":  {
    "integration_score":  float,   # mean abs(off-diagonal) — how globally coupled
    "parallel_score":     float,   # mean of negative correlations (more negative = more parallel)
    "hub_node":           dim_id,  # most-connected dim (highest sum of |correlation|)
    "isolated_node":      dim_id,  # least-connected dim
    "n_timesteps":        int,
    "min_timesteps_for_reliability": int  # warning threshold
  },
  "warnings": [list of strings],
}

Edge threshold: |correlation| > 0.30 to draw the edge (else we omit it
from the edges list to keep the graph readable; the full matrix is
always returned for the heatmap).

Edge cases:
- timeseries shorter than 5 timesteps → return a "too_short" warning
  and skip metric computation. The frontend renders "Not enough data
  for a reliable connectivity map" instead of meaningless near-zero/NaN
  correlations.
- a flat dimension (zero variance) → its row/column is NaN under
  Pearson; we replace with 0.0 and add a per-dim "flat" warning.
"""
from __future__ import annotations

import math
from typing import Any

# Stable display order for the 7 cortical systems. Matches the rest of
# the codebase (matches Codex's mockup ordering and the audio/video
# results timeseries cards).
DIM_ORDER = [
    "attention_salience",
    "memory_encoding",
    "personal_resonance",
    "gut_reaction",
    "social_thinking",
    "language_depth",
    "brain_effort",
]

EDGE_THRESHOLD = 0.30
MIN_TIMESTEPS_FOR_RELIABILITY = 5


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Pure-Python Pearson r. Returns 0.0 when either series is flat
    (zero variance) — preferable to NaN in the result payload."""
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    num = 0.0
    sx = 0.0
    sy = 0.0
    for i in range(n):
        dx = xs[i] - mx
        dy = ys[i] - my
        num += dx * dy
        sx += dx * dx
        sy += dy * dy
    if sx <= 0.0 or sy <= 0.0:
        return 0.0
    r = num / math.sqrt(sx * sy)
    # Clip floating-point drift outside [-1, 1].
    if r > 1.0:
        return 1.0
    if r < -1.0:
        return -1.0
    return r


def _gather_timeseries(rows: list[dict[str, Any]], side: str) -> dict[str, list[float]]:
    field = "timeseries_a" if side == "a" else "timeseries_b"
    out: dict[str, list[float]] = {}
    for row in rows:
        key = row.get("key")
        ts = row.get(field) or []
        if not key or not isinstance(ts, list):
            continue
        out[key] = [float(v) for v in ts if v is not None]
    return out


def _row_for(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    for r in rows:
        if r.get("key") == key:
            return r
    return {}


def _empty_payload(warning: str) -> dict[str, Any]:
    return {
        "dim_keys": [],
        "labels": [],
        "regions": [],
        "matrix": [],
        "edges": [],
        "metrics": {
            "integration_score": 0.0,
            "parallel_score": 0.0,
            "hub_node": None,
            "isolated_node": None,
            "n_timesteps": 0,
            "min_timesteps_for_reliability": MIN_TIMESTEPS_FOR_RELIABILITY,
        },
        "warnings": [warning],
    }


def compute_connectivity_for_side(
    dimension_rows: list[dict[str, Any]],
    side: str,
) -> dict[str, Any]:
    """Compute the connectivity payload for Version A or B."""
    series = _gather_timeseries(dimension_rows, side)
    # Only include dims we actually have timeseries for, in canonical order.
    keys = [k for k in DIM_ORDER if k in series]
    if not keys:
        return _empty_payload("No dimensional timeseries available for this side.")
    n_timesteps = min(len(series[k]) for k in keys)
    warnings: list[str] = []
    if n_timesteps < MIN_TIMESTEPS_FOR_RELIABILITY:
        warnings.append(
            f"Only {n_timesteps} timestep{'s' if n_timesteps != 1 else ''} available — "
            f"correlations need at least {MIN_TIMESTEPS_FOR_RELIABILITY} to be reliable. "
            "Connectivity map suppressed."
        )
        out = _empty_payload(warnings[0])
        out["metrics"]["n_timesteps"] = n_timesteps
        return out

    # Truncate every series to n_timesteps so all correlations use the same window.
    truncated = {k: series[k][:n_timesteps] for k in keys}

    # Flag dimensions with zero variance (would silently produce r=0 across the row).
    flat_dims = [k for k in keys if max(truncated[k]) - min(truncated[k]) <= 1e-9]
    for k in flat_dims:
        warnings.append(f"{k} timeseries is flat (zero variance) — its correlations are reported as 0.")

    matrix: list[list[float]] = []
    for i, ki in enumerate(keys):
        row: list[float] = []
        for j, kj in enumerate(keys):
            if i == j:
                row.append(1.0)
            else:
                row.append(round(_pearson(truncated[ki], truncated[kj]), 4))
        matrix.append(row)

    edges: list[dict[str, Any]] = []
    for i, ki in enumerate(keys):
        for j in range(i + 1, len(keys)):
            kj = keys[j]
            r = matrix[i][j]
            if abs(r) >= EDGE_THRESHOLD:
                edges.append({
                    "source": ki,
                    "target": kj,
                    "weight": round(abs(r), 4),
                    "correlation": round(r, 4),
                    "type": "positive" if r >= 0 else "negative",
                })
    edges.sort(key=lambda e: e["weight"], reverse=True)

    # Off-diagonal stats. Each pair counted once.
    off_diag: list[float] = []
    negatives: list[float] = []
    per_node_strength: dict[str, float] = {k: 0.0 for k in keys}
    for i, ki in enumerate(keys):
        for j in range(i + 1, len(keys)):
            r = matrix[i][j]
            off_diag.append(abs(r))
            if r < 0:
                negatives.append(r)
            per_node_strength[ki] += abs(r)
            per_node_strength[keys[j]] += abs(r)
    integration_score = round(sum(off_diag) / len(off_diag), 4) if off_diag else 0.0
    parallel_score = round(sum(negatives) / len(negatives), 4) if negatives else 0.0
    if per_node_strength:
        hub_node = max(per_node_strength, key=per_node_strength.get)
        isolated_node = min(per_node_strength, key=per_node_strength.get)
    else:
        hub_node = None
        isolated_node = None

    labels = [_row_for(dimension_rows, k).get("label") or k for k in keys]
    regions = [_row_for(dimension_rows, k).get("region") or "" for k in keys]

    return {
        "dim_keys": keys,
        "labels": labels,
        "regions": regions,
        "matrix": matrix,
        "edges": edges,
        "metrics": {
            "integration_score": integration_score,
            "parallel_score": parallel_score,
            "hub_node": hub_node,
            "isolated_node": isolated_node,
            "n_timesteps": n_timesteps,
            "min_timesteps_for_reliability": MIN_TIMESTEPS_FOR_RELIABILITY,
            "per_node_strength": {k: round(v, 4) for k, v in per_node_strength.items()},
        },
        "warnings": warnings,
    }


def compute_connectivity_both_sides(
    dimension_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Convenience for the worker + local API: connectivity for A, B,
    plus the B−A delta matrix highlighting most-changed pairs."""
    side_a = compute_connectivity_for_side(dimension_rows, "a")
    side_b = compute_connectivity_for_side(dimension_rows, "b")
    payload: dict[str, Any] = {"a": side_a, "b": side_b}

    # Comparison delta — only when both sides have a usable matrix.
    if side_a.get("matrix") and side_b.get("matrix") and side_a["dim_keys"] == side_b["dim_keys"]:
        keys = side_a["dim_keys"]
        delta_matrix: list[list[float]] = []
        deltas: list[dict[str, Any]] = []
        for i, ki in enumerate(keys):
            row: list[float] = []
            for j, kj in enumerate(keys):
                d = round(side_b["matrix"][i][j] - side_a["matrix"][i][j], 4)
                row.append(d)
                if i < j:
                    deltas.append({
                        "source": ki,
                        "target": kj,
                        "delta": d,
                        "abs_delta": abs(d),
                    })
            delta_matrix.append(row)
        deltas.sort(key=lambda d: d["abs_delta"], reverse=True)
        payload["delta"] = {
            "matrix": delta_matrix,
            "top_changed": deltas[:5],
        }
    return payload
