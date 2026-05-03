"""Content assembler — the 3-tier priority resolver.

For each renderable slot, the assembler picks a value in this order:

  1. manual_overrides/{comparison_id}/{slot_address}.json   (typed JSON, schema-validated)
  2. outputs/{comparison_id}/raw/{slot_address}.json        (LLM-generated, validation passed)
  3. assets/slot_defaults.json                              (hand-written generic fallback)

If an override file exists but fails schema validation, an `slot_override_invalid`
audit event is emitted and the assembler falls through to the LLM raw output.

The output is a content.json matching content.schema.json. Frontend reads it
directly — no further content logic anywhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit_log import AuditLogger
from .ids import hash_file, now_iso


REPO_ROOT = Path(__file__).resolve().parents[3]
ASSETS_DIR = REPO_ROOT / "backend" / "results" / "assets"


# ────────────────────────────────────────────────────────────
# Slot address registry
# ────────────────────────────────────────────────────────────

# Generic addresses, no creator names. Frontend reads slots[address].
# Recipe-match has a different shape; chord_meanings/chord_moments are
# handled specially because they're per-chord.
SCALAR_SLOTS: tuple[str, ...] = (
    "headline",
    "body",
    "frame2_sub",
    "recipe_description.video_a",
    "recipe_description.video_b",
    "coupling_callouts.video_a.strongest",
    "coupling_callouts.video_a.weakest",
    "coupling_callouts.video_a.anti",
    "coupling_callouts.video_b.strongest",
    "coupling_callouts.video_b.weakest",
    "coupling_callouts.video_b.anti",
)

RECIPE_MATCH_SLOTS: tuple[str, ...] = (
    "recipe_match.video_a",
    "recipe_match.video_b",
)


# ────────────────────────────────────────────────────────────
# Result types
# ────────────────────────────────────────────────────────────

@dataclass
class ResolvedSlot:
    value: Any
    source: str   # "override" | "llm" | "fallback" | "library"
    status: str   # "ok" | "validation_failed" | "generation_failed" | "override_invalid" | "missing_inputs" | "generic"
    raw_path: str | None
    errors: list[str]


# ────────────────────────────────────────────────────────────
# Assembler
# ────────────────────────────────────────────────────────────

class ContentAssembler:
    def __init__(
        self,
        comparison_id: str,
        run_id: str,
        outputs_dir: Path,
        overrides_dir: Path,
        audit: AuditLogger,
    ) -> None:
        self.comparison_id = comparison_id
        self.run_id = run_id
        self.outputs_dir = outputs_dir
        self.overrides_dir = overrides_dir
        self.audit = audit

        self._defaults = json.loads((ASSETS_DIR / "slot_defaults.json").read_text())

    # ------- per-slot resolution -------

    def resolve_scalar(self, slot_address: str, fallback_key: str) -> ResolvedSlot:
        """Resolve a slot whose value is a string."""
        # 1. override
        override = self._read_override(slot_address)
        if override is not None:
            ok, errs = self._validate_scalar_override(override)
            if ok:
                self.audit.emit("slot_override_used", slot=slot_address)
                return ResolvedSlot(
                    value=override["value"],
                    source="override",
                    status="ok",
                    raw_path=None,
                    errors=[],
                )
            self.audit.emit(
                "slot_override_invalid",
                slot=slot_address,
                error_code="OVERRIDE_SCHEMA_INVALID",
                error_detail="; ".join(errs),
            )
            # fall through to raw

        # 2. LLM raw
        raw = self._read_raw(slot_address)
        if raw is not None and raw.get("validation", {}).get("passed") and raw.get("selected"):
            return ResolvedSlot(
                value=raw["selected"],
                source="llm",
                status="ok",
                raw_path=str(self._raw_path(slot_address)),
                errors=[],
            )

        # 3. fallback
        self.audit.emit(
            "slot_fallback_used",
            slot=slot_address,
            error_code=("RAW_VALIDATION_FAILED" if raw is not None else "RAW_NOT_FOUND"),
        )
        default = self._defaults.get(fallback_key, self._defaults.get("headline"))
        return ResolvedSlot(
            value=default["value"],
            source="fallback",
            status="generic",
            raw_path=None,
            errors=[],
        )

    def resolve_recipe_match(self, slot_address: str) -> ResolvedSlot:
        """recipe_match.video_X — value is a dict {library_id, name, confidence, score_breakdown, rationale}."""
        # override
        override = self._read_override(slot_address)
        if override is not None:
            ok, errs = self._validate_recipe_match_override(override)
            if ok:
                self.audit.emit("slot_override_used", slot=slot_address)
                return ResolvedSlot(
                    value=override["value"],
                    source="override",
                    status="ok",
                    raw_path=None,
                    errors=[],
                )
            self.audit.emit(
                "slot_override_invalid",
                slot=slot_address,
                error_code="OVERRIDE_SCHEMA_INVALID",
                error_detail="; ".join(errs),
            )

        raw = self._read_raw(slot_address)
        if raw is not None and raw.get("validation", {}).get("passed") and isinstance(raw.get("selected"), dict):
            return ResolvedSlot(
                value=raw["selected"],
                source="llm",
                status="ok",
                raw_path=str(self._raw_path(slot_address)),
                errors=[],
            )

        self.audit.emit(
            "slot_fallback_used",
            slot=slot_address,
            error_code=("RAW_VALIDATION_FAILED" if raw is not None else "RAW_NOT_FOUND"),
        )
        default = self._defaults["recipe_match"]
        return ResolvedSlot(
            value=default["value"],
            source="fallback",
            status="generic",
            raw_path=None,
            errors=[],
        )

    # ------- file IO -------

    def _override_path(self, slot_address: str) -> Path:
        # slot_address may contain dots; preserve them as filename parts.
        return self.overrides_dir / f"{slot_address}.json"

    def _raw_path(self, slot_address: str) -> Path:
        return self.outputs_dir / "raw" / f"{slot_address}.json"

    def _read_override(self, slot_address: str) -> dict[str, Any] | None:
        path = self._override_path(slot_address)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            self.audit.emit(
                "slot_override_invalid",
                slot=slot_address,
                error_code="OVERRIDE_NOT_JSON",
                error_detail=f"override file at {path} is not valid JSON",
            )
            return None

    def _read_raw(self, slot_address: str) -> dict[str, Any] | None:
        path = self._raw_path(slot_address)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return None

    # ------- minimal override schema validators (full schema-validation is
    # cheap to add in Phase 1; for now we enforce the shape we read) -------

    @staticmethod
    def _validate_scalar_override(d: dict[str, Any]) -> tuple[bool, list[str]]:
        errs: list[str] = []
        if "value" not in d or not isinstance(d["value"], str):
            errs.append("missing or non-string 'value'")
        return (not errs, errs)

    @staticmethod
    def _validate_recipe_match_override(d: dict[str, Any]) -> tuple[bool, list[str]]:
        errs: list[str] = []
        v = d.get("value")
        if not isinstance(v, dict):
            errs.append("'value' must be an object")
            return False, errs
        for required in ("library_id", "name", "confidence", "rationale"):
            if required not in v:
                errs.append(f"missing '{required}'")
        if "confidence" in v and not (0.0 <= float(v["confidence"]) <= 1.0):
            errs.append("'confidence' must be in [0, 1]")
        return (not errs, errs)


# ────────────────────────────────────────────────────────────
# Top-level assembly
# ────────────────────────────────────────────────────────────

def asset_hashes() -> dict[str, str]:
    """Hash every asset that influences content. Logged in content.json.assets."""
    return {
        "recipe_library_version": json.loads((ASSETS_DIR / "recipe_library.json").read_text())["version"],
        "chord_library_version":  json.loads((ASSETS_DIR / "chord_library.json").read_text())["version"],
        "voice_exemplars_hash":   hash_file(str(ASSETS_DIR / "voice_exemplars.json")),
        "prompt_templates_hash":  _hash_prompt_templates_dir(),
        "slot_defaults_hash":     hash_file(str(ASSETS_DIR / "slot_defaults.json")),
    }


def _hash_prompt_templates_dir() -> str:
    """Stable hash across the prompt_templates directory."""
    import hashlib
    pt_dir = ASSETS_DIR.parent / "prompt_templates"
    if not pt_dir.exists():
        return "empty"
    h = hashlib.sha256()
    for path in sorted(pt_dir.glob("*.txt")):
        h.update(path.name.encode())
        h.update(b"\0")
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


def assemble_content(
    *,
    comparison_id: str,
    run_id: str,
    analysis_version: str,
    inputs: dict[str, Any],
    outputs_dir: Path,
    overrides_dir: Path,
    audit: AuditLogger,
) -> dict[str, Any]:
    """Build a full content.json from inputs + raw outputs + overrides + defaults."""
    asm = ContentAssembler(comparison_id, run_id, outputs_dir, overrides_dir, audit)

    chord_lib = json.loads((ASSETS_DIR / "chord_library.json").read_text())
    chord_meanings: dict[str, Any] = {}
    for chord in chord_lib["chords"]:
        chord_meanings[chord["id"]] = {
            "value": {
                "id":            chord["id"],
                "name":          chord["name"],
                "micro_label":   chord["micro_label"],
                "formula_human": chord["formula_human"],
                "meaning":       chord["meaning"],
                "citations":     chord.get("citations", []),
            },
            "source": "library",
            "status": "ok",
        }

    # chord_moments — one entry per chord firing across both videos. Phase 1+
    # populates context.value via chord_context slot. Phase 0 fills with fallback.
    chord_moments: list[dict[str, Any]] = []
    for vid_key in ("video_a", "video_b"):
        vid = inputs[vid_key]
        for i, ev in enumerate(vid.get("chord_events", [])):
            slot_addr = f"chord_moments[{len(chord_moments)}].context"
            resolved = asm.resolve_scalar(slot_addr, fallback_key="chord_context")
            chord_moments.append({
                "index": len(chord_moments),
                "video": vid_key,
                "chord_id": ev["chord_id"],
                "timestamp_seconds": ev["timestamp_seconds"],
                "quote": ev.get("quote"),
                "context": _slot_to_dict(resolved),
            })

    content = {
        "schema_version":   "results_content.v1",
        "comparison_id":    comparison_id,
        "run_id":           run_id,
        "analysis_version": analysis_version,
        "generated_at":     now_iso(),
        "assets":           asset_hashes(),
        "videos": {
            "video_a": _video_meta(inputs["video_a"]),
            "video_b": _video_meta(inputs["video_b"]),
        },
        "slots": {
            "headline":   _slot_to_dict(asm.resolve_scalar("headline", "headline")),
            "body":       _slot_to_dict(asm.resolve_scalar("body", "body")),
            "frame2_sub": _slot_to_dict(asm.resolve_scalar("frame2_sub", "frame2_sub")),

            "recipe_match": {
                "video_a": _slot_to_dict(asm.resolve_recipe_match("recipe_match.video_a")),
                "video_b": _slot_to_dict(asm.resolve_recipe_match("recipe_match.video_b")),
            },
            "recipe_description": {
                "video_a": _slot_to_dict(asm.resolve_scalar("recipe_description.video_a", "recipe_description")),
                "video_b": _slot_to_dict(asm.resolve_scalar("recipe_description.video_b", "recipe_description")),
            },

            "chord_meanings": chord_meanings,
            "chord_moments":  chord_moments,

            "coupling_callouts": {
                "video_a": {
                    "strongest": _slot_to_dict(asm.resolve_scalar("coupling_callouts.video_a.strongest", "coupling_callout")),
                    "weakest":   _slot_to_dict(asm.resolve_scalar("coupling_callouts.video_a.weakest",   "coupling_callout")),
                    "anti":      _slot_to_dict(asm.resolve_scalar("coupling_callouts.video_a.anti",      "coupling_callout")),
                },
                "video_b": {
                    "strongest": _slot_to_dict(asm.resolve_scalar("coupling_callouts.video_b.strongest", "coupling_callout")),
                    "weakest":   _slot_to_dict(asm.resolve_scalar("coupling_callouts.video_b.weakest",   "coupling_callout")),
                    "anti":      _slot_to_dict(asm.resolve_scalar("coupling_callouts.video_b.anti",      "coupling_callout")),
                },
            },
        },
    }
    audit.emit("content_assembled", data={"slot_count": _count_slots(content["slots"])})
    return content


def _video_meta(v: dict[str, Any]) -> dict[str, Any]:
    """Strip a normalised VideoSignature down to schema-conforming videoMeta.

    The full signature (system_means, peaks, chord_events, couplings) is kept
    in inputs.json for the frontend to pull when it needs charts. content.json
    only carries display metadata.
    """
    return {
        "id":               v["id"],
        "display_name":     v.get("display_name", v["id"]),
        "creator":          v.get("creator"),
        "title":            v.get("title"),
        "duration_seconds": v.get("duration_seconds"),
    }


def _slot_to_dict(r: ResolvedSlot) -> dict[str, Any]:
    return {
        "value":    r.value,
        "source":   r.source,
        "status":   r.status,
        "raw_path": r.raw_path,
        "errors":   r.errors,
    }


def _count_slots(slots: dict[str, Any]) -> int:
    """Count leaf slots for telemetry."""
    n = 0
    if "headline" in slots: n += 1
    if "body" in slots: n += 1
    if "frame2_sub" in slots: n += 1
    n += 2  # recipe_match
    n += 2  # recipe_description
    n += len(slots.get("chord_meanings", {}))
    n += len(slots.get("chord_moments", []))
    n += 6  # coupling callouts
    return n
