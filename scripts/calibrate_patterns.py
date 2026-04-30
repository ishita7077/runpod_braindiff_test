"""Re-derive pattern thresholds from a real result corpus.

Why: v1 ships with conservative defaults (60th–70th percentile of activation
on our demo corpus). When real production results accumulate, run this
script with their dimension timeseries to derive empirically-grounded
thresholds and write them back to pattern-definitions.json.

Usage:
    python3 scripts/calibrate_patterns.py CORPUS_DIR
where CORPUS_DIR contains result JSON files (one per job) with the same
shape the worker emits: each file has `dimensions[i].timeseries_a` and
`timeseries_b`.

The script is conservative by design: thresholds are clamped to never go
below the v1 defaults (so calibration can't accidentally make patterns
hyperactive). The user has to manually accept lowered thresholds by
editing pattern-definitions.json after reviewing the proposed values.

Outputs:
- prints per-pattern, per-dim threshold suggestions
- writes scripts/proposed-thresholds.json with the computed percentiles
- does NOT modify pattern-definitions.json directly
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import quantiles
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFS_PATH = REPO / "frontend_new" / "data" / "pattern-definitions.json"


def load_corpus(corpus_dir: Path) -> dict[str, list[float]]:
    """Walk every result JSON in `corpus_dir` and concatenate all per-dim
    timeseries values across all jobs. Returns {dim_key: [...all values...]}.

    Skips files that don't have the expected shape — corpus collection is
    fuzzy and you should be able to point this at a directory that includes
    cached debugging output without it crashing.
    """
    pooled: dict[str, list[float]] = {}
    for path in sorted(corpus_dir.glob("**/*.json")):
        try:
            payload = json.loads(path.read_text())
        except Exception:
            continue
        dims = payload.get("dimensions") or payload.get("result", {}).get("dimensions") or []
        if not isinstance(dims, list):
            continue
        for row in dims:
            key = row.get("key")
            if not key:
                continue
            for field in ("timeseries_a", "timeseries_b"):
                ts = row.get(field) or []
                if not isinstance(ts, list):
                    continue
                pooled.setdefault(key, []).extend(float(v) for v in ts if v is not None)
    return pooled


def percentile(values: list[float], pct: float) -> float:
    """Return the `pct`th percentile of `values` (0–100)."""
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    qs = quantiles(values, n=100, method="inclusive")
    idx = max(0, min(99, int(pct) - 1))
    return float(qs[idx])


def propose(pooled: dict[str, list[float]], pct: float, defs: dict[str, Any]) -> dict[str, Any]:
    """For each pattern's contributing dim, propose a new threshold = the
    `pct`th percentile of pooled values for that dim. Clamp to never go
    below the existing v1 default (we don't want calibration to make
    detection more permissive than the documented baseline)."""
    proposals: dict[str, dict[str, float]] = {}
    for pattern in defs.get("patterns", []):
        pid = pattern["id"]
        proposals[pid] = {}
        thresholds = pattern.get("thresholds", {})
        for dim_id, current in thresholds.items():
            empirical = percentile(pooled.get(dim_id, []), pct)
            # Conservative clamp: never go below current v1 default.
            proposed = max(current, empirical)
            proposals[pid][dim_id] = round(proposed, 3)
    return proposals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "corpus_dir",
        type=Path,
        help="Directory of result JSON files to calibrate against",
    )
    parser.add_argument(
        "--percentile",
        type=float,
        default=70.0,
        help="Percentile of pooled activations to use as the threshold (default: 70)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "scripts" / "proposed-thresholds.json",
        help="Where to write proposed thresholds JSON",
    )
    args = parser.parse_args()

    if not args.corpus_dir.is_dir():
        print(f"error: corpus_dir not found: {args.corpus_dir}", file=sys.stderr)
        sys.exit(2)

    defs = json.loads(DEFS_PATH.read_text())
    pooled = load_corpus(args.corpus_dir)
    if not pooled:
        print("warning: no per-dim timeseries values found in corpus_dir", file=sys.stderr)
        sys.exit(1)

    print(f"corpus: {sum(len(v) for v in pooled.values())} pooled values across {len(pooled)} dimensions")
    proposals = propose(pooled, args.percentile, defs)

    print(f"\nProposed thresholds at the {args.percentile}th percentile (clamped to current floor):")
    for pid, thresholds in proposals.items():
        print(f"  {pid}:")
        current = next((p["thresholds"] for p in defs["patterns"] if p["id"] == pid), {})
        for dim_id, val in thresholds.items():
            cur = current.get(dim_id, 0.0)
            arrow = "→" if abs(val - cur) > 0.005 else "="
            print(f"    {dim_id}: {cur:.2f} {arrow} {val:.2f}")

    args.out.write_text(json.dumps(
        {
            "calibrated_at_percentile": args.percentile,
            "n_pooled_values_per_dim": {k: len(v) for k, v in pooled.items()},
            "proposed_thresholds": proposals,
        },
        indent=2,
    ))
    print(f"\nWrote proposals to {args.out}")
    print("Review, then manually update pattern-definitions.json if you accept any.")


if __name__ == "__main__":
    main()
