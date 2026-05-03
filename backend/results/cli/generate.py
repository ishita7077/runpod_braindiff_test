"""Top-level orchestrator: turn a comparison input into a content.json.

Phase 0 behaviour:
  * Reads inputs from a file or builds a sample comparison.
  * Skips actual LLM generation (no slot runners wired in yet).
  * Runs the content assembler — every slot resolves to its fallback default.
  * Writes outputs/{comparison_id}/content.json.
  * Emits audit events for the full lifecycle.

Phase 1 wires the headline slot runner in; subsequent phases add the rest.

CLI:
  python -m backend.results.cli.generate --inputs path/to/inputs.json
  python -m backend.results.cli.generate --sample cleo-mrbeast
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..lib.audit_log import AuditLogger
from ..lib.content_assembler import assemble_content
from ..lib.ids import comparison_id, run_id as new_run_id
from ..lib.input_normalizer import (
    InputValidationError,
    NormalizedInputs,
    input_hash,
    normalize_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_ROOT = REPO_ROOT / "outputs"
AUDIT_ROOT = REPO_ROOT / "audit_log"
OVERRIDES_ROOT = REPO_ROOT / "manual_overrides"
SAMPLES_DIR = REPO_ROOT / "backend" / "results" / "assets" / "samples"


# ────────────────────────────────────────────────────────────
# Sample comparison fixtures (used until real TRIBE inputs arrive)
# ────────────────────────────────────────────────────────────

def _sample_inputs(name: str) -> dict:
    """Built-in sample. Phase 0 ships one: cleo vs mrbeast 60s clips."""
    if name != "cleo-mrbeast":
        raise SystemExit(f"unknown sample: {name!r}. available: cleo-mrbeast")
    return {
        "video_a": {
            "id": "cleo-quantum-2024-04",
            "display_name": "Cleo Abram",
            "creator": "Cleo Abram",
            "title": "Quantum Computing Explained",
            "duration_seconds": 60.0,
            "system_means": {
                "personal_resonance": 0.42,
                "attention":          0.62,
                "brain_effort":       0.58,
                "gut_reaction":       0.28,
                "memory_encoding":    0.66,
                "social_thinking":    0.41,
                "language_depth":     0.71,
            },
            "system_peaks": {
                "personal_resonance": {"time": 8.0,  "value": 0.55},
                "attention":          {"time": 22.0, "value": 0.78},
                "brain_effort":       {"time": 32.0, "value": 0.82},
                "gut_reaction":       {"time": 4.0,  "value": 0.41},
                "memory_encoding":    {"time": 18.0, "value": 0.81},
                "social_thinking":    {"time": 28.0, "value": 0.55},
                "language_depth":     {"time": 32.0, "value": 0.86},
            },
            "chord_events": [
                {"chord_id": "learning-moment", "timestamp_seconds": 18.0, "duration_seconds": 2.0, "quote": "Imagine searching a library..."},
                {"chord_id": "reasoning-beat",  "timestamp_seconds": 32.0, "duration_seconds": 4.0, "quote": "Quantum computing isn't about being faster..."}
            ],
            "integration_score": 0.41,
            "hub_node": "language_depth",
            "couplings": [
                {"system_a": "memory_encoding", "system_b": "language_depth", "r":  0.65},
                {"system_a": "personal_resonance", "system_b": "gut_reaction", "r":  0.18},
                {"system_a": "attention", "system_b": "brain_effort", "r":  0.18},
            ],
        },
        "video_b": {
            "id": "mrbeast-circle-2024-03",
            "display_name": "MrBeast",
            "creator": "MrBeast",
            "title": "Last to Leave Circle Wins $500,000",
            "duration_seconds": 60.0,
            "system_means": {
                "personal_resonance": 0.61,
                "attention":          0.74,
                "brain_effort":       0.32,
                "gut_reaction":       0.69,
                "memory_encoding":    0.39,
                "social_thinking":    0.46,
                "language_depth":     0.38,
            },
            "system_peaks": {
                "personal_resonance": {"time": 47.0, "value": 0.78},
                "attention":          {"time": 8.0,  "value": 0.88},
                "brain_effort":       {"time": 30.0, "value": 0.42},
                "gut_reaction":       {"time": 8.0,  "value": 0.91},
                "memory_encoding":    {"time": 22.0, "value": 0.51},
                "social_thinking":    {"time": 35.0, "value": 0.58},
                "language_depth":     {"time": 18.0, "value": 0.49},
            },
            "chord_events": [
                {"chord_id": "visceral-hit",     "timestamp_seconds": 8.0,  "duration_seconds": 2.0, "quote": "I'll give one million dollars..."},
                {"chord_id": "emotional-impact", "timestamp_seconds": 47.0, "duration_seconds": 1.0, "quote": "You can change your life..."}
            ],
            "integration_score": 0.22,
            "hub_node": "gut_reaction",
            "couplings": [
                {"system_a": "attention", "system_b": "gut_reaction", "r":  0.62},
                {"system_a": "brain_effort", "system_b": "gut_reaction", "r": -0.32},
                {"system_a": "memory_encoding", "system_b": "language_depth", "r":  0.14},
            ],
        },
    }


# ────────────────────────────────────────────────────────────
# Orchestrator
# ────────────────────────────────────────────────────────────

def run(
    raw_inputs: dict,
    *,
    analysis_version: str = "tribev2.2026.05",
) -> Path:
    """End-to-end: normalise → assemble → write content.json."""
    rid = new_run_id()

    # We need a comparison_id to name our log file. Compute it from raw IDs.
    cmp_id = comparison_id(
        raw_inputs.get("video_a", {}).get("id", "unknown_a"),
        raw_inputs.get("video_b", {}).get("id", "unknown_b"),
        analysis_version,
    )

    audit = AuditLogger(comparison_id=cmp_id, run_id=rid, log_dir=AUDIT_ROOT)
    audit.emit("comparison_started", data={"analysis_version": analysis_version})

    try:
        inputs = normalize_inputs(raw_inputs, analysis_version=analysis_version)
    except InputValidationError as exc:
        audit.emit("input_invalid", error_code="INPUT_MISSING_FIELDS", error_detail=str(exc))
        audit.emit("comparison_failed", error_code="INPUT_MISSING_FIELDS", error_detail=str(exc))
        raise

    audit.emit("input_normalized", input_hash=input_hash(inputs))

    # Persist normalised inputs alongside outputs for reproducibility.
    out_dir = OUTPUTS_ROOT / cmp_id
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    inputs_path = out_dir / "inputs.json"
    inputs_path.write_text(json.dumps(inputs.to_dict(), indent=2))

    # Build the content. Phase 0 has no slot runners wired in, so every slot
    # resolves to its fallback default. Phase 1 wires headline.
    overrides_dir = OVERRIDES_ROOT / cmp_id
    overrides_dir.mkdir(parents=True, exist_ok=True)

    content = assemble_content(
        comparison_id=cmp_id,
        run_id=rid,
        analysis_version=analysis_version,
        inputs=inputs.to_dict(),
        outputs_dir=out_dir,
        overrides_dir=overrides_dir,
        audit=audit,
    )

    content_path = out_dir / "content.json"
    content_path.write_text(json.dumps(content, indent=2))
    audit.emit("comparison_completed", data={"content_path": str(content_path)})

    return content_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate a Brain Diff results page content.json")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--inputs", type=Path, help="Path to inputs.json")
    src.add_argument("--sample", choices=["cleo-mrbeast"], help="Built-in sample comparison")
    p.add_argument("--analysis-version", default="tribev2.2026.05")
    args = p.parse_args(argv)

    raw = _sample_inputs(args.sample) if args.sample else json.loads(args.inputs.read_text())
    content_path = run(raw, analysis_version=args.analysis_version)
    print(f"OK content_path={content_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
