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

import asyncio

from ..lib.audit_log import AuditLogger
from ..lib.content_assembler import assemble_content
from ..lib.ids import comparison_id, run_id as new_run_id
from ..lib.input_normalizer import (
    InputValidationError,
    NormalizedInputs,
    input_hash,
    normalize_inputs,
)
from ..lib.model_manager import get_model_manager
from ..slots.base import Slot, SlotResult
from ..slots.headline import HeadlineSlot
from ..slots.recipe_match import RecipeMatchSlot
from ..slots.recipe_description import RecipeDescriptionSlot
from ..slots.chord_context import ChordContextSlot
from ..slots.body import BodySlot
from ..slots.frame2_sub import Frame2SubSlot
from ..slots.coupling_callout import CouplingCalloutSlot
from ..lib.library_matcher import match_recipe


REPO_ROOT = Path(__file__).resolve().parents[3]
# Outputs live under frontend_new/ so Vercel serves them as static assets.
# Audit log + overrides stay at repo root (operational, not user-facing).
OUTPUTS_ROOT = REPO_ROOT / "frontend_new" / "outputs"
AUDIT_ROOT = REPO_ROOT / "audit_log"
OVERRIDES_ROOT = REPO_ROOT / "manual_overrides"
SAMPLES_DIR = REPO_ROOT / "backend" / "results" / "assets" / "samples"


# ────────────────────────────────────────────────────────────
# Sample comparison fixtures (used until real TRIBE inputs arrive)
# ────────────────────────────────────────────────────────────

SAMPLE_NAMES = ("cleo-mrbeast", "veritasium-dudeperfect", "vox-shock")


def _sample_inputs(name: str) -> dict:
    """Built-in samples. 3 production samples for the launch."""
    if name not in SAMPLE_NAMES:
        raise SystemExit(f"unknown sample: {name!r}. available: {SAMPLE_NAMES}")
    if name == "veritasium-dudeperfect":
        return _sample_veritasium_dudeperfect()
    if name == "vox-shock":
        return _sample_vox_shock()
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


def _sample_veritasium_dudeperfect() -> dict:
    """Cold-cognitive-work vs visceral-hook contrast."""
    return {
        "video_a": {
            "id": "veritasium-pi-2024-09",
            "display_name": "Veritasium",
            "creator": "Veritasium",
            "title": "The Discovery That Transformed Pi",
            "duration_seconds": 60.0,
            "system_means": {
                "personal_resonance": 0.31, "attention": 0.66, "brain_effort": 0.72,
                "gut_reaction": 0.22, "memory_encoding": 0.62, "social_thinking": 0.38,
                "language_depth": 0.74,
            },
            "system_peaks": {
                "personal_resonance": {"time": 12.0, "value": 0.42},
                "attention":          {"time": 28.0, "value": 0.81},
                "brain_effort":       {"time": 38.0, "value": 0.89},
                "gut_reaction":       {"time": 5.0,  "value": 0.34},
                "memory_encoding":    {"time": 24.0, "value": 0.78},
                "social_thinking":    {"time": 45.0, "value": 0.52},
                "language_depth":     {"time": 38.0, "value": 0.91},
            },
            "chord_events": [
                {"chord_id": "reasoning-beat", "timestamp_seconds": 38.0, "duration_seconds": 4.0,
                 "quote": "It turned out the answer had been hiding in plain sight..."},
                {"chord_id": "learning-moment", "timestamp_seconds": 24.0, "duration_seconds": 2.0,
                 "quote": "Imagine integrating along this curve..."},
            ],
            "integration_score": 0.42,
            "hub_node": "language_depth",
            "couplings": [
                {"system_a": "language_depth", "system_b": "memory_encoding", "r":  0.71},
                {"system_a": "brain_effort", "system_b": "language_depth", "r":  0.68},
                {"system_a": "personal_resonance", "system_b": "gut_reaction", "r":  0.12},
            ],
        },
        "video_b": {
            "id": "dudeperfect-trick-2024-08",
            "display_name": "Dude Perfect",
            "creator": "Dude Perfect",
            "title": "Trick Shot Battle",
            "duration_seconds": 60.0,
            "system_means": {
                "personal_resonance": 0.55, "attention": 0.78, "brain_effort": 0.29,
                "gut_reaction": 0.71, "memory_encoding": 0.34, "social_thinking": 0.51,
                "language_depth": 0.32,
            },
            "system_peaks": {
                "personal_resonance": {"time": 52.0, "value": 0.74},
                "attention":          {"time": 7.0,  "value": 0.92},
                "brain_effort":       {"time": 28.0, "value": 0.38},
                "gut_reaction":       {"time": 7.0,  "value": 0.94},
                "memory_encoding":    {"time": 18.0, "value": 0.45},
                "social_thinking":    {"time": 41.0, "value": 0.62},
                "language_depth":     {"time": 22.0, "value": 0.41},
            },
            "chord_events": [
                {"chord_id": "visceral-hit", "timestamp_seconds": 7.0, "duration_seconds": 2.0,
                 "quote": "No way that just went in..."},
                {"chord_id": "emotional-impact", "timestamp_seconds": 52.0, "duration_seconds": 1.0,
                 "quote": "Boom! Champion!"},
            ],
            "integration_score": 0.19,
            "hub_node": "gut_reaction",
            "couplings": [
                {"system_a": "attention", "system_b": "gut_reaction", "r":  0.74},
                {"system_a": "brain_effort", "system_b": "gut_reaction", "r": -0.41},
                {"system_a": "memory_encoding", "system_b": "language_depth", "r":  0.18},
            ],
        },
    }


def _sample_vox_shock() -> dict:
    """Cinematic build vs empty calories — story arc vs pure shock."""
    return {
        "video_a": {
            "id": "vox-meaning-2024-11",
            "display_name": "Vox",
            "creator": "Vox",
            "title": "The Search for the Meaning of the Universe",
            "duration_seconds": 60.0,
            "system_means": {
                "personal_resonance": 0.58, "attention": 0.61, "brain_effort": 0.52,
                "gut_reaction": 0.34, "memory_encoding": 0.61, "social_thinking": 0.55,
                "language_depth": 0.66,
            },
            "system_peaks": {
                "personal_resonance": {"time": 8.0,  "value": 0.71},
                "attention":          {"time": 35.0, "value": 0.74},
                "brain_effort":       {"time": 41.0, "value": 0.69},
                "gut_reaction":       {"time": 12.0, "value": 0.48},
                "memory_encoding":    {"time": 28.0, "value": 0.78},
                "social_thinking":    {"time": 22.0, "value": 0.71},
                "language_depth":     {"time": 35.0, "value": 0.81},
            },
            "chord_events": [
                {"chord_id": "story-integration", "timestamp_seconds": 28.0, "duration_seconds": 3.0,
                 "quote": "And then a strange pattern emerged..."},
                {"chord_id": "social-resonance", "timestamp_seconds": 22.0, "duration_seconds": 2.0,
                 "quote": "Carl Sagan wrote about this..."},
            ],
            "integration_score": 0.52,
            "hub_node": "memory_encoding",
            "couplings": [
                {"system_a": "memory_encoding", "system_b": "social_thinking", "r":  0.62},
                {"system_a": "language_depth", "system_b": "memory_encoding", "r":  0.58},
                {"system_a": "personal_resonance", "system_b": "gut_reaction", "r":  0.21},
            ],
        },
        "video_b": {
            "id": "ragebait-shock-2024-12",
            "display_name": "Shock Channel",
            "creator": "Anonymous",
            "title": "You Won't Believe What Happened",
            "duration_seconds": 60.0,
            "system_means": {
                "personal_resonance": 0.32, "attention": 0.71, "brain_effort": 0.21,
                "gut_reaction": 0.78, "memory_encoding": 0.28, "social_thinking": 0.30,
                "language_depth": 0.31,
            },
            "system_peaks": {
                "personal_resonance": {"time": 4.0,  "value": 0.44},
                "attention":          {"time": 4.0,  "value": 0.88},
                "brain_effort":       {"time": 18.0, "value": 0.31},
                "gut_reaction":       {"time": 4.0,  "value": 0.95},
                "memory_encoding":    {"time": 38.0, "value": 0.41},
                "social_thinking":    {"time": 28.0, "value": 0.42},
                "language_depth":     {"time": 12.0, "value": 0.38},
            },
            "chord_events": [
                {"chord_id": "visceral-hit", "timestamp_seconds": 4.0, "duration_seconds": 2.0,
                 "quote": "...what happened next was unbelievable"},
            ],
            "integration_score": 0.14,
            "hub_node": "gut_reaction",
            "couplings": [
                {"system_a": "attention", "system_b": "gut_reaction", "r":  0.81},
                {"system_a": "memory_encoding", "system_b": "language_depth", "r":  0.05},
                {"system_a": "brain_effort", "system_b": "gut_reaction", "r": -0.28},
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

    overrides_dir = OVERRIDES_ROOT / cmp_id
    overrides_dir.mkdir(parents=True, exist_ok=True)

    # Run all enabled slots through the model manager (parallel where possible).
    manager = get_model_manager()
    audit.emit("model_manager_started", data={"backend": manager.backend.model_id})
    slots: list[Slot] = _enabled_slots(inputs)
    if slots:
        asyncio.run(_run_slots(slots, inputs, cmp_id, rid, out_dir, manager, audit))

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


def _enabled_slots(inputs: NormalizedInputs | None = None) -> list[Slot]:
    """Every slot the pipeline runs. Order doesn't matter — they run in parallel."""
    slots: list[Slot] = [
        HeadlineSlot(),
        BodySlot(),
        RecipeMatchSlot(video_key="video_a"),
        RecipeMatchSlot(video_key="video_b"),
        RecipeDescriptionSlot(video_key="video_a"),
        RecipeDescriptionSlot(video_key="video_b"),
    ]
    if inputs is not None:
        match_a = match_recipe(inputs.video_a)
        match_b = match_recipe(inputs.video_b)
        slots.append(Frame2SubSlot(
            recipe_a_name=match_a.name,
            recipe_b_name=match_b.name,
        ))
        # One coupling callout slot per (video, type).
        for vid_key in ("video_a", "video_b"):
            for ctype in ("strongest", "weakest", "anti"):
                slots.append(CouplingCalloutSlot(video_key=vid_key, coupling_type=ctype))

        # Per-firing chord context slots — global firing index across both videos.
        firing_index = 0
        for vid_key in ("video_a", "video_b"):
            video = getattr(inputs, vid_key)
            for ev in video.chord_events:
                slots.append(ChordContextSlot(
                    firing_index=firing_index,
                    video_key=vid_key,
                    event=ev,
                ))
                firing_index += 1
    return slots


async def _run_slots(
    slots: list[Slot],
    inputs: NormalizedInputs,
    cmp_id: str,
    rid: str,
    out_dir: Path,
    manager,
    audit: AuditLogger,
) -> list[SlotResult]:
    coros = [
        slot.run(
            inputs=inputs,
            comparison_id=cmp_id,
            run_id=rid,
            outputs_dir=out_dir,
            manager=manager,
            audit=audit,
        )
        for slot in slots
    ]
    return await asyncio.gather(*coros)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate a Brain Diff results page content.json")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--inputs", type=Path, help="Path to inputs.json")
    src.add_argument("--sample", choices=list(SAMPLE_NAMES), help="Built-in sample comparison")
    p.add_argument("--analysis-version", default="tribev2.2026.05")
    args = p.parse_args(argv)

    raw = _sample_inputs(args.sample) if args.sample else json.loads(args.inputs.read_text())
    content_path = run(raw, analysis_version=args.analysis_version)
    print(f"OK content_path={content_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
