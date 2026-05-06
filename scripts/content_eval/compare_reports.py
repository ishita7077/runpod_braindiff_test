#!/usr/bin/env python3
"""Diff two content_eval reports — Phase D.2 model promotion gate.

Reads two reports produced by run_eval.py and prints:
  * side-by-side summary metrics
  * per-fixture deltas in latency, fallback rate, brief presence
  * a clear pass/fail line for the promotion rule

Promotion rule (matches the plan):
  * candidate must NOT regress fallback_rate by more than 0.05
  * candidate must NOT regress avg latency by more than 50 percent
  * candidate brief_present_rate must be ≥ baseline brief_present_rate
  * human review still required — this is the cheap automated gate

Usage:
    python -m scripts.content_eval.compare_reports \\
        reports/eval_1b.json reports/eval_4b.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _summary_table(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[tuple[str, Any, Any, str]]:
    rows: list[tuple[str, Any, Any, str]] = []
    sb = baseline["summary"]
    sc = candidate["summary"]
    for key in ("fixtures_run", "fixtures_ok", "avg_content_latency_ms",
                "max_fallback_rate", "mean_fallback_rate",
                "schema_pass_rate", "brief_present_rate",
                "total_recommendations"):
        bval = sb.get(key)
        cval = sc.get(key)
        delta = ""
        if isinstance(bval, (int, float)) and isinstance(cval, (int, float)):
            delta = f"{cval - bval:+.4g}"
        rows.append((key, bval, cval, delta))
    return rows


def _per_fixture_deltas(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[dict[str, Any]]:
    by_name_b = {r["fixture"]: r for r in baseline["per_fixture"]}
    by_name_c = {r["fixture"]: r for r in candidate["per_fixture"]}
    out: list[dict[str, Any]] = []
    for name in sorted(set(by_name_b) | set(by_name_c)):
        b = by_name_b.get(name, {})
        c = by_name_c.get(name, {})
        out.append({
            "fixture": name,
            "baseline_latency_ms": b.get("latency_ms"),
            "candidate_latency_ms": c.get("latency_ms"),
            "baseline_fallback": b.get("fallback_rate"),
            "candidate_fallback": c.get("fallback_rate"),
            "baseline_brief": b.get("brief_present"),
            "candidate_brief": c.get("brief_present"),
        })
    return out


def _promote_decision(baseline: dict[str, Any], candidate: dict[str, Any]) -> tuple[bool, list[str]]:
    sb = baseline["summary"]
    sc = candidate["summary"]
    reasons: list[str] = []
    ok = True
    fb_delta = sc["mean_fallback_rate"] - sb["mean_fallback_rate"]
    if fb_delta > 0.05:
        ok = False
        reasons.append(f"fallback_rate regressed by {fb_delta:+.3f} (>0.05 threshold)")
    if sb["avg_content_latency_ms"] > 0:
        lat_ratio = sc["avg_content_latency_ms"] / sb["avg_content_latency_ms"]
        if lat_ratio > 1.5:
            ok = False
            reasons.append(f"avg latency increased by {lat_ratio:.2f}x (>1.5 threshold)")
    if sc["brief_present_rate"] < sb["brief_present_rate"]:
        ok = False
        reasons.append(
            f"brief_present_rate regressed: {sb['brief_present_rate']:.2f} -> {sc['brief_present_rate']:.2f}"
        )
    if not reasons:
        reasons.append("automated thresholds met; human quality review still required")
    return ok, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", help="baseline report JSON (e.g. eval_1b.json)")
    parser.add_argument("candidate", help="candidate report JSON (e.g. eval_4b.json)")
    args = parser.parse_args()

    baseline = json.loads(Path(args.baseline).read_text())
    candidate = json.loads(Path(args.candidate).read_text())

    print(f"baseline:  {baseline.get('label')}  ({args.baseline})")
    print(f"candidate: {candidate.get('label')}  ({args.candidate})\n")

    print("SUMMARY METRICS")
    print(f"  {'metric':<32} {'baseline':>14} {'candidate':>14} {'delta':>12}")
    for key, b, c, delta in _summary_table(baseline, candidate):
        print(f"  {key:<32} {str(b):>14} {str(c):>14} {delta:>12}")

    print("\nPER-FIXTURE DELTAS")
    for row in _per_fixture_deltas(baseline, candidate):
        print(
            f"  {row['fixture']:<32}"
            f" lat {row['baseline_latency_ms']}->{row['candidate_latency_ms']}"
            f" · fb {row['baseline_fallback']}->{row['candidate_fallback']}"
            f" · brief {row['baseline_brief']}->{row['candidate_brief']}"
        )

    ok, reasons = _promote_decision(baseline, candidate)
    print("\nAUTOMATED PROMOTION DECISION:", "PASS (auto-only)" if ok else "FAIL")
    for r in reasons:
        print(f"  - {r}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
