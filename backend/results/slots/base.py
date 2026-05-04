"""Slot runner — the abstraction every slot reuses.

A Slot is one piece of generated content (headline, body, recipe_description, ...).
Each subclass:
  * declares its `slot_address` (the generic path used in raw/, overrides/, content.json)
  * declares its `template_name` (filename in prompt_templates/)
  * implements `build_template_context(inputs)` to fill the prompt
  * implements `parse_selected(model_text)` to extract the final value
  * provides a `validator: BaseValidator`

The runner handles:
  * loading the prompt template + voice exemplars
  * computing a deterministic seed per (comparison_id, slot_address)
  * calling ModelManager (queued, timed, bounded)
  * validating, retrying once on failure with temperature bumped
  * writing raw/{slot_address}.json with the full audit trail
  * emitting audit events

If both attempts fail validation the runner returns SlotResult(failed=True) and
the assembler will fall through to the default. The fallback flag is set.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..lib.audit_log import AuditLogger
from ..lib.ids import deterministic_seed, hash_string, now_iso
from ..lib.input_normalizer import NormalizedInputs
from ..lib.model_manager import GenerationRequest, ModelManager
from ..validators.base import BaseValidator, ValidationResult


REPO_ROOT = Path(__file__).resolve().parents[3]
ASSETS_DIR = REPO_ROOT / "backend" / "results" / "assets"
TEMPLATES_DIR = REPO_ROOT / "backend" / "results" / "prompt_templates"


# ────────────────────────────────────────────────────────────
# Result type
# ────────────────────────────────────────────────────────────

@dataclass
class SlotResult:
    slot_address: str
    selected: Any | None
    candidates: list[Any]
    validation: ValidationResult
    raw_path: Path | None
    attempts: int
    latency_ms: int
    succeeded: bool


# ────────────────────────────────────────────────────────────
# Voice exemplars loader (cached)
# ────────────────────────────────────────────────────────────

_voice_exemplars_cache: dict[str, Any] | None = None


def voice_exemplars() -> dict[str, Any]:
    global _voice_exemplars_cache
    if _voice_exemplars_cache is None:
        _voice_exemplars_cache = json.loads((ASSETS_DIR / "voice_exemplars.json").read_text())
    return _voice_exemplars_cache


# ────────────────────────────────────────────────────────────
# Base slot class
# ────────────────────────────────────────────────────────────

class Slot:
    slot_address: str = "base"
    template_name: str = ""
    max_new_tokens: int = 120
    temperature: float = 0.4
    top_p: float = 0.9
    do_sample: bool = False  # production default = greedy
    output_is_json: bool = False  # most slots return text; some (recipe_match) return JSON

    def __init__(self, validator: BaseValidator) -> None:
        self.validator = validator

    # ------- subclass hooks -------

    def build_template_context(self, inputs: NormalizedInputs) -> dict[str, Any]:
        """Return a dict of {placeholder_name: value} for prompt rendering."""
        raise NotImplementedError

    def parse_selected(self, model_text: str) -> Any:
        """Take raw model output and return the final 'selected' value.

        Default: strip and return as-is. Override for JSON slots.
        """
        return model_text.strip()

    # ------- prompt rendering -------

    def render_prompt(self, ctx: dict[str, Any]) -> str:
        """Render the template by replacing {placeholder} tokens.

        Simple substitution; we don't need full Jinja2. Missing keys raise.
        """
        template = (TEMPLATES_DIR / self.template_name).read_text()
        # Use a minimal {key} substitution that leaves unrelated braces intact.
        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in ctx:
                raise KeyError(f"prompt template {self.template_name} references {{{key}}} but ctx has no such key")
            return str(ctx[key])
        return re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", repl, template)

    # ------- the runner -------

    async def run(
        self,
        *,
        inputs: NormalizedInputs,
        comparison_id: str,
        run_id: str,
        outputs_dir: Path,
        manager: ModelManager,
        audit: AuditLogger,
    ) -> SlotResult:
        audit.emit("slot_started", slot=self.slot_address)
        start = time.perf_counter()

        ctx = self.build_template_context(inputs)
        prompt = self.render_prompt(ctx)
        prompt_hash = hash_string(prompt)
        audit.emit("slot_prompt_rendered", slot=self.slot_address, prompt_hash=prompt_hash)

        seed = deterministic_seed(comparison_id, self.slot_address)
        candidates: list[Any] = []
        validation: ValidationResult = ValidationResult(passed=False)
        attempts = 0
        last_error: str | None = None

        # Two attempts: first deterministic, retry with sampling at temperature 0.5.
        for attempt in (1, 2):
            attempts = attempt
            req = GenerationRequest(
                prompt=prompt,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature if attempt == 1 else 0.5,
                top_p=self.top_p,
                do_sample=False if attempt == 1 else True,
                seed=seed + (attempt - 1),  # second attempt: nudge seed
            )

            audit.emit("slot_model_called", slot=self.slot_address, attempt=attempt, prompt_hash=prompt_hash)

            try:
                resp = await manager.generate(req)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                audit.emit(
                    "slot_model_failed",
                    slot=self.slot_address,
                    attempt=attempt,
                    error_code="MODEL_CALL_FAILED",
                    error_detail=last_error,
                )
                if attempt == 2:
                    break
                audit.emit("slot_retry_started", slot=self.slot_address, attempt=2)
                continue

            audit.emit(
                "slot_model_returned",
                slot=self.slot_address,
                attempt=attempt,
                latency_ms=resp.latency_ms,
            )

            try:
                selected = self.parse_selected(resp.text)
            except Exception as exc:
                last_error = f"PARSE_ERROR: {exc}"
                audit.emit(
                    "slot_validation_failed",
                    slot=self.slot_address,
                    attempt=attempt,
                    error_code="OUTPUT_UNPARSEABLE",
                    error_detail=str(exc),
                )
                if attempt == 2:
                    break
                audit.emit("slot_retry_started", slot=self.slot_address, attempt=2)
                continue

            candidates.append(selected)
            validation = self.validator.validate(selected)

            if validation.passed:
                audit.emit("slot_validation_passed", slot=self.slot_address, attempt=attempt)
                break

            audit.emit(
                "slot_validation_failed",
                slot=self.slot_address,
                attempt=attempt,
                error_code=validation.errors[0].code if validation.errors else "VALIDATION_FAILED",
                error_detail="; ".join(e.detail for e in validation.errors),
            )
            if attempt == 1:
                audit.emit("slot_retry_started", slot=self.slot_address, attempt=2)

        latency_ms = int((time.perf_counter() - start) * 1000)

        # Write raw_slot.json regardless of success — assembler decides what to do with it.
        raw_path = outputs_dir / "raw" / f"{self.slot_address}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_doc = {
            "schema_version":  "raw_slot.v1",
            "slot":            self.slot_address,
            "comparison_id":   comparison_id,
            "run_id":          run_id,
            "generated_at":    now_iso(),
            "model": {
                "model_id":       manager.backend.model_id,
                "model_revision": manager.backend.model_revision,
                "seed":           seed,
                "do_sample":      self.do_sample,
                "temperature":    self.temperature,
                "top_p":          self.top_p,
                "max_new_tokens": self.max_new_tokens,
            },
            "asset_hashes": _asset_hashes_for_slot(),
            "prompt_rendered": prompt,
            "candidates": candidates,
            "selected":   candidates[-1] if (candidates and validation.passed) else None,
            "attempts":   attempts,
            "validation": validation.as_dict(),
            "latency_ms": latency_ms,
        }
        raw_path.write_text(json.dumps(raw_doc, indent=2, ensure_ascii=False))

        succeeded = validation.passed
        audit.emit(
            "slot_completed",
            slot=self.slot_address,
            attempt=attempts,
            latency_ms=latency_ms,
            raw_output_path=str(raw_path),
            error_code=None if succeeded else "VALIDATION_FAILED_FINAL",
            error_detail=None if succeeded else last_error,
        )
        return SlotResult(
            slot_address=self.slot_address,
            selected=raw_doc["selected"],
            candidates=candidates,
            validation=validation,
            raw_path=raw_path,
            attempts=attempts,
            latency_ms=latency_ms,
            succeeded=succeeded,
        )


# ────────────────────────────────────────────────────────────
# Asset hashing for raw_slot provenance
# ────────────────────────────────────────────────────────────

def _asset_hashes_for_slot() -> dict[str, Any]:
    from ..lib.ids import hash_file
    return {
        "voice_exemplars_hash": hash_file(str(ASSETS_DIR / "voice_exemplars.json")),
        "recipe_library_version": json.loads((ASSETS_DIR / "recipe_library.json").read_text())["version"],
        "chord_library_version":  json.loads((ASSETS_DIR / "chord_library.json").read_text())["version"],
    }
