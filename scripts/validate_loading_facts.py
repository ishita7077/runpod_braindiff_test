#!/usr/bin/env python3
"""Validate frontend/data/tribe_loading_facts.json shape (run in CI or before commit)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "frontend" / "data" / "tribe_loading_facts.json"


def main() -> int:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    meta = data.get("meta")
    if not isinstance(meta, dict):
        print("FAIL: missing meta object", file=sys.stderr)
        return 1
    for k in ("content_version", "last_reviewed", "review_cadence_days"):
        if k not in meta:
            print(f"FAIL: meta missing {k}", file=sys.stderr)
            return 1
    facts = data.get("facts")
    if not isinstance(facts, list) or len(facts) < 1:
        print("FAIL: facts must be a non-empty list", file=sys.stderr)
        return 1
    for i, f in enumerate(facts):
        if not isinstance(f, dict):
            print(f"FAIL: facts[{i}] not an object", file=sys.stderr)
            return 1
        for k in ("tag", "title", "body"):
            if k not in f or not isinstance(f[k], str) or not str(f[k]).strip():
                print(f"FAIL: facts[{i}] missing or empty {k}", file=sys.stderr)
                return 1
        if "source_url" in f and f["source_url"] is not None:
            if not isinstance(f["source_url"], str) or not f["source_url"].startswith("http"):
                print(f"FAIL: facts[{i}] source_url must be http(s) URL", file=sys.stderr)
                return 1
    print("OK tribe_loading_facts.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
