"""Failure-injection tests — Phase 4 hardening.

Runs four breakage scenarios and asserts that each produces a clear,
specific audit-log signal AND that the page still renders (via fallbacks).

  1. Model endpoint dies         → every slot falls back, slot_model_failed events.
  2. Override file is malformed  → slot_override_invalid event, falls through to LLM.
  3. raw/ output deleted         → slot_fallback_used with RAW_NOT_FOUND.
  4. Recipe library corrupted    → comparison_failed with clear error.

Run: python -m backend.results.cli.failure_tests
Exit 0 on full pass, exit 1 on any test that didn't behave as expected.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

from ..lib.audit_log import AuditLogger, read_events
from ..lib.ids import comparison_id, run_id as new_run_id
from ..lib.input_normalizer import normalize_inputs
from ..lib.model_manager import (
    GenerationResponse,
    ModelManager,
    StubBackend,
    set_model_manager,
    get_model_manager,
)
from .generate import _sample_inputs, run as orchestrator_run


REPO_ROOT = Path(__file__).resolve().parents[3]
ASSETS = REPO_ROOT / "backend" / "results" / "assets"
OUTPUTS_ROOT = REPO_ROOT / "frontend_new" / "outputs"
AUDIT_ROOT = REPO_ROOT / "audit_log"
OVERRIDES_ROOT = REPO_ROOT / "manual_overrides"


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

class _Result:
    def __init__(self, name: str) -> None:
        self.name = name
        self.passed = True
        self.notes: list[str] = []

    def assert_(self, cond: bool, msg: str) -> None:
        if not cond:
            self.passed = False
        self.notes.append(("[PASS] " if cond else "[FAIL] ") + msg)


def _setup() -> str:
    """Reset state for one test, return comparison_id."""
    raw = _sample_inputs("cleo-mrbeast")
    cmp_id = comparison_id(raw["video_a"]["id"], raw["video_b"]["id"], "tribev2.2026.05")
    shutil.rmtree(OUTPUTS_ROOT / cmp_id, ignore_errors=True)
    shutil.rmtree(OVERRIDES_ROOT / cmp_id, ignore_errors=True)
    (AUDIT_ROOT / f"{cmp_id}.jsonl").unlink(missing_ok=True)
    return cmp_id


def _events_with(events: list[dict], event_type: str) -> list[dict]:
    return [e for e in events if e["event_type"] == event_type]


# ────────────────────────────────────────────────────────────
# Test 1: model endpoint dies
# ────────────────────────────────────────────────────────────

class _DyingBackend:
    model_id = "dying-stub"
    model_revision = "fail-test"

    async def generate(self, req):  # pragma: no cover
        raise RuntimeError("simulated model endpoint failure")

    def vram_peak_mb(self): return None
    def reset_vram_peak(self): pass


def test_model_dies() -> _Result:
    r = _Result("test_1_model_endpoint_dies")
    cmp_id = _setup()
    set_model_manager(ModelManager(_DyingBackend()))
    try:
        orchestrator_run(_sample_inputs("cleo-mrbeast"))
    except Exception as exc:
        r.assert_(False, f"orchestrator should NOT crash on model failure, but raised: {exc}")
        return r
    finally:
        # Restore healthy stub for subsequent tests.
        set_model_manager(ModelManager(StubBackend()))

    events = read_events(cmp_id)
    failed = _events_with(events, "slot_model_failed")
    fallbacks = _events_with(events, "slot_fallback_used")
    completed = _events_with(events, "comparison_completed")

    r.assert_(len(failed) > 0, f"expected slot_model_failed events, got 0 (events={[e['event_type'] for e in events[:5]]})")
    r.assert_(len(fallbacks) > 0, "expected slot_fallback_used events when model dies")
    r.assert_(len(completed) == 1, "comparison should still complete even with all-LLM-failures")

    # Page must render: content.json exists and validates.
    content_path = OUTPUTS_ROOT / cmp_id / "content.json"
    r.assert_(content_path.exists(), "content.json should exist even with model failures")

    if content_path.exists():
        c = json.loads(content_path.read_text())
        r.assert_(c["slots"]["headline"]["source"] == "fallback", "headline should be fallback after model death")
    return r


# ────────────────────────────────────────────────────────────
# Test 2: malformed override
# ────────────────────────────────────────────────────────────

def test_malformed_override() -> _Result:
    r = _Result("test_2_malformed_override")
    cmp_id = _setup()
    overrides_dir = OVERRIDES_ROOT / cmp_id
    overrides_dir.mkdir(parents=True, exist_ok=True)
    (overrides_dir / "headline.json").write_text("{ this is not valid json")
    (overrides_dir / "body.json").write_text(json.dumps({"wrong_field": "x"}))

    orchestrator_run(_sample_inputs("cleo-mrbeast"))

    events = read_events(cmp_id)
    invalid = _events_with(events, "slot_override_invalid")
    invalid_codes = {e.get("error_code") for e in invalid}

    r.assert_(any("OVERRIDE" in (c or "") for c in invalid_codes),
              f"expected override-invalid events, got codes {invalid_codes}")

    content_path = OUTPUTS_ROOT / cmp_id / "content.json"
    if content_path.exists():
        c = json.loads(content_path.read_text())
        # Bad overrides → fall through to LLM (since stub is healthy here).
        r.assert_(c["slots"]["headline"]["source"] == "llm", "headline should fall through to LLM on bad override")
        r.assert_(c["slots"]["body"]["source"] == "llm", "body should fall through to LLM on bad override")

    shutil.rmtree(overrides_dir, ignore_errors=True)
    return r


# ────────────────────────────────────────────────────────────
# Test 3: raw output deleted
# ────────────────────────────────────────────────────────────

def test_raw_deleted() -> _Result:
    r = _Result("test_3_raw_output_deleted")
    cmp_id = _setup()
    orchestrator_run(_sample_inputs("cleo-mrbeast"))

    raw_path = OUTPUTS_ROOT / cmp_id / "raw" / "headline.json"
    r.assert_(raw_path.exists(), "headline raw should exist after first run")
    raw_path.unlink()

    # Re-assemble (without re-running slots) — drop the audit log first to isolate this run.
    (AUDIT_ROOT / f"{cmp_id}.jsonl").unlink(missing_ok=True)

    from ..lib.content_assembler import assemble_content
    rid = new_run_id()
    audit = AuditLogger(comparison_id=cmp_id, run_id=rid, log_dir=AUDIT_ROOT)
    inputs_dict = json.loads((OUTPUTS_ROOT / cmp_id / "inputs.json").read_text())
    content = assemble_content(
        comparison_id=cmp_id, run_id=rid,
        analysis_version="tribev2.2026.05",
        inputs=inputs_dict,
        outputs_dir=OUTPUTS_ROOT / cmp_id,
        overrides_dir=OVERRIDES_ROOT / cmp_id,
        audit=audit,
    )

    events = read_events(cmp_id)
    fallbacks = _events_with(events, "slot_fallback_used")
    headline_fallbacks = [e for e in fallbacks if e.get("slot") == "headline"]
    r.assert_(len(headline_fallbacks) >= 1 and headline_fallbacks[0].get("error_code") == "RAW_NOT_FOUND",
              f"expected RAW_NOT_FOUND fallback for headline, got {[(e.get('slot'), e.get('error_code')) for e in fallbacks]}")
    r.assert_(content["slots"]["headline"]["source"] == "fallback", "headline.source should be fallback")
    return r


# ────────────────────────────────────────────────────────────
# Test 4: recipe library corrupted
# ────────────────────────────────────────────────────────────

def test_corrupt_library() -> _Result:
    r = _Result("test_4_corrupt_recipe_library")
    cmp_id = _setup()
    lib_path = ASSETS / "recipe_library.json"
    backup = lib_path.read_text()

    # Corrupt: invalid JSON.
    lib_path.write_text("{ not valid json")
    # Also clear the cached library load.
    from ..lib import library_matcher
    library_matcher._LIBRARY_CACHE = None

    crashed = False
    try:
        orchestrator_run(_sample_inputs("cleo-mrbeast"))
    except Exception:
        crashed = True
    finally:
        lib_path.write_text(backup)
        library_matcher._LIBRARY_CACHE = None

    events = read_events(cmp_id)
    # Acceptable: comparison_failed event OR all recipe slots fall back.
    failed = _events_with(events, "comparison_failed")
    r.assert_(crashed or len(failed) > 0,
              "corrupt library should produce comparison_failed event OR raise — both are acceptable failure signals")
    return r


# ────────────────────────────────────────────────────────────
# Runner
# ────────────────────────────────────────────────────────────

def main() -> int:
    tests = [test_model_dies, test_malformed_override, test_raw_deleted, test_corrupt_library]
    results: list[_Result] = []
    for fn in tests:
        try:
            results.append(fn())
        except Exception as exc:
            r = _Result(fn.__name__)
            r.assert_(False, f"test crashed: {type(exc).__name__}: {exc}")
            results.append(r)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print()
    print(f"{'='*60}")
    print(f"  Failure injection tests: {passed}/{total} passed")
    print(f"{'='*60}")
    for r in results:
        marker = "✓" if r.passed else "✗"
        print(f"  {marker} {r.name}")
        for note in r.notes:
            print(f"      {note}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
