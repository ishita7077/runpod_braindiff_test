"""braindiff debug — inspect what happened to a comparison.

This is the "point to something when it breaks" tool. Reads
audit_log/{comparison_id}.jsonl and renders a human-readable trace.

Usage:
  python -m backend.results.cli.debug <comparison_id>
  python -m backend.results.cli.debug <comparison_id> --slot headline
  python -m backend.results.cli.debug <comparison_id> --errors-only
  python -m backend.results.cli.debug <comparison_id> --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..lib.audit_log import read_events


REPO_ROOT = Path(__file__).resolve().parents[3]
AUDIT_ROOT = REPO_ROOT / "audit_log"


# ANSI colour helpers — tasteful, no rainbows.
_RESET = "\x1b[0m"
_DIM   = "\x1b[2m"
_BOLD  = "\x1b[1m"
_RED   = "\x1b[31m"
_YEL   = "\x1b[33m"
_GRN   = "\x1b[32m"
_BLU   = "\x1b[34m"
_MAG   = "\x1b[35m"


# Map event types to a colour family. Errors are red, fallbacks yellow,
# successes green, infrastructural events blue.
_EVENT_COLOURS: dict[str, str] = {
    "comparison_started":            _BLU,
    "comparison_completed":          _GRN,
    "comparison_failed":             _RED,
    "input_normalized":              _BLU,
    "input_invalid":                 _RED,
    "model_manager_started":         _BLU,
    "model_manager_failed":          _RED,
    "slot_started":                  _DIM,
    "slot_prompt_rendered":          _DIM,
    "slot_model_called":             _DIM,
    "slot_model_returned":           _DIM,
    "slot_model_failed":             _RED,
    "slot_validation_passed":        _GRN,
    "slot_validation_failed":        _RED,
    "slot_retry_started":            _YEL,
    "slot_fallback_used":            _YEL,
    "slot_override_used":            _MAG,
    "slot_override_invalid":         _RED,
    "slot_completed":                _GRN,
    "library_match_scored":          _BLU,
    "library_match_low_confidence":  _YEL,
    "content_assembled":             _GRN,
    "content_schema_invalid":        _RED,
    "frontend_contract_validated":   _GRN,
}


def _fmt_event(ev: dict) -> str:
    colour = _EVENT_COLOURS.get(ev["event_type"], "")
    parts = [
        f"{_DIM}{ev['timestamp'][11:23]}{_RESET}",
        f"{colour}{_BOLD}{ev['event_type']:<32}{_RESET}",
    ]
    if ev.get("slot"):
        parts.append(f"slot={ev['slot']}")
    if ev.get("attempt") is not None:
        parts.append(f"attempt={ev['attempt']}")
    if ev.get("error_code"):
        parts.append(f"{_RED}{ev['error_code']}{_RESET}")
    if ev.get("error_detail"):
        parts.append(f"— {ev['error_detail']}")
    if ev.get("latency_ms") is not None:
        parts.append(f"{_DIM}({ev['latency_ms']}ms){_RESET}")
    if ev.get("raw_output_path"):
        parts.append(f"{_DIM}raw={ev['raw_output_path']}{_RESET}")
    return "  ".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Inspect a comparison's audit log")
    p.add_argument("comparison_id", help="16-hex-char comparison ID")
    p.add_argument("--slot", help="Filter to events for one slot")
    p.add_argument("--errors-only", action="store_true", help="Only error/fallback/invalid events")
    p.add_argument("--json", action="store_true", help="Raw JSONL output")
    p.add_argument("--audit-dir", default=AUDIT_ROOT, type=Path)
    args = p.parse_args(argv)

    events = read_events(args.comparison_id, log_dir=args.audit_dir)
    if not events:
        print(f"No audit log found for comparison_id={args.comparison_id} in {args.audit_dir}")
        return 1

    # Filters.
    if args.slot:
        events = [e for e in events if e.get("slot") == args.slot]
    if args.errors_only:
        events = [
            e for e in events
            if e["event_type"] in {
                "input_invalid", "slot_validation_failed", "slot_model_failed",
                "slot_override_invalid", "slot_fallback_used", "model_manager_failed",
                "library_match_low_confidence", "content_schema_invalid",
                "comparison_failed",
            }
        ]

    if args.json:
        for e in events:
            print(json.dumps(e))
        return 0

    print(f"{_BOLD}=== comparison {args.comparison_id} — {len(events)} events ==={_RESET}")
    for e in events:
        print(_fmt_event(e))

    # Summary.
    failed = sum(1 for e in events if "failed" in e["event_type"] or "invalid" in e["event_type"])
    fallback = sum(1 for e in events if e["event_type"] == "slot_fallback_used")
    override = sum(1 for e in events if e["event_type"] == "slot_override_used")
    print()
    print(f"{_BOLD}summary:{_RESET}  errors={failed}  fallbacks={fallback}  overrides={override}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
