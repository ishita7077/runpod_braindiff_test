#!/usr/bin/env python3
"""Phase D content-pipeline evaluation harness.

Runs every fixture in scripts/content_eval/fixtures/ through
generate_content_for_worker, captures content_audit + content_model + per-
fixture metrics (latency, fallback rate, brief grounding), and emits a JSON
report.

Usage:
    # Full run on RunPod (real Gemma):
    python -m scripts.content_eval.run_eval \\
        --output reports/eval_1b.json \\
        --label "gemma-3-1b-it"

    # Stub mode (no GPU, sanity check the harness on CI):
    python -m scripts.content_eval.run_eval --stub --output reports/eval_stub.json

Switching models for the ladder (Phase D.2):
    BRAIN_DIFF_CONTENT_MODEL=google/gemma-3-4b-it \\
    python -m scripts.content_eval.run_eval --output reports/eval_4b.json --label "gemma-3-4b-it"

Use compare_reports.py to diff two report JSONs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.results.lib.evidence_packet import (
    build_evidence_packet,
    collect_valid_evidence_refs,
)
from backend.results.lib.input_normalizer import (
    CANONICAL_SYSTEMS,
    NormalizedInputs,
)
from backend.results.worker_integration import (
    _build_video,
    generate_content_for_worker,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_fixtures() -> list[dict[str, Any]]:
    out = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        out.append(json.loads(path.read_text()))
    return out


def _run_fixture(fix: dict[str, Any], use_stub: bool) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = generate_content_for_worker(
            video_a_id=fix["video_a_id"],
            video_b_id=fix["video_b_id"],
            video_a_title=fix["video_a_title"],
            video_b_title=fix["video_b_title"],
            duration_a_s=float(fix["duration_a_s"]),
            duration_b_s=float(fix["duration_b_s"]),
            timeseries_a=fix["timeseries_a"],
            timeseries_b=fix["timeseries_b"],
            transcript_segments_a=fix["transcript_segments_a"],
            transcript_segments_b=fix["transcript_segments_b"],
            analysis_version="eval-harness",
            use_stub=use_stub,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "fixture": fix["name"],
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    content = result.get("content") or {}
    audit = result.get("content_audit") or {}
    model = result.get("content_model") or {}
    brief_slot = (content.get("slots") or {}).get("analysis_brief") or {}
    brief_value = brief_slot.get("value") if isinstance(brief_slot, dict) else None
    brief_present = bool(brief_value)

    return {
        "fixture": fix["name"],
        "ok": True,
        "latency_ms": elapsed_ms,
        "content_audit": audit,
        "content_model": model,
        "brief_present": brief_present,
        "brief_thesis": (brief_value or {}).get("thesis") if brief_present else None,
        "brief_recommendations_count": len((brief_value or {}).get("recommendations") or []) if brief_present else 0,
        "brief_confidence": (brief_value or {}).get("confidence") if brief_present else None,
        "headline": (content.get("slots", {}).get("headline") or {}).get("value"),
        "body": (content.get("slots", {}).get("body") or {}).get("value"),
        "fallback_rate": audit.get("fallback_rate", 0.0),
        "schema_version": content.get("schema_version"),
        "input_audit": result.get("input_audit"),
    }


def _summarise(per_fixture: list[dict[str, Any]]) -> dict[str, Any]:
    runs_ok = [r for r in per_fixture if r.get("ok")]
    n = len(runs_ok)
    avg_lat = sum(r.get("latency_ms", 0) for r in runs_ok) / n if n else 0.0
    fallbacks = [r.get("fallback_rate", 0.0) for r in runs_ok]
    schema_pass = sum(1 for r in runs_ok if r.get("schema_version") == "results_content.v1") / n if n else 0.0
    brief_pass = sum(1 for r in runs_ok if r.get("brief_present")) / n if n else 0.0
    rec_total = sum(r.get("brief_recommendations_count", 0) for r in runs_ok)
    return {
        "fixtures_run": len(per_fixture),
        "fixtures_ok": n,
        "avg_content_latency_ms": int(avg_lat),
        "max_fallback_rate": max(fallbacks) if fallbacks else 0.0,
        "mean_fallback_rate": sum(fallbacks) / n if n else 0.0,
        "schema_pass_rate": schema_pass,
        "brief_present_rate": brief_pass,
        "total_recommendations": rec_total,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="path to write the JSON report")
    parser.add_argument("--label", default=None, help="human label for this run (defaults to BRAIN_DIFF_CONTENT_MODEL)")
    parser.add_argument("--stub", action="store_true", help="use the stub backend (no GPU)")
    args = parser.parse_args()

    fixtures = _load_fixtures()
    if not fixtures:
        print(f"no fixtures in {FIXTURES_DIR}", file=sys.stderr)
        return 2

    label = args.label or os.getenv("BRAIN_DIFF_CONTENT_MODEL", "unknown")
    print(f"running {len(fixtures)} fixtures · label={label} · stub={args.stub}")

    per_fixture: list[dict[str, Any]] = []
    for fix in fixtures:
        print(f"  • {fix['name']} ...", flush=True)
        per_fixture.append(_run_fixture(fix, use_stub=args.stub))

    report = {
        "schema_version": "content_eval.v1",
        "label": label,
        "stub": args.stub,
        "summary": _summarise(per_fixture),
        "per_fixture": per_fixture,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nwrote {out_path}")
    summary = report["summary"]
    print("summary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0 if summary["fixtures_ok"] == summary["fixtures_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
