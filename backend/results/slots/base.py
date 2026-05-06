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

    # Phase C.5 — sampled generation + repair loop.
    #
    # Old behaviour: attempt 1 greedy, attempt 2 sampled. Two shots, no
    # awareness of WHY attempt 1 failed.
    #
    # New behaviour:
    #   1. sample (temperature self.temperature, do_sample=self.do_sample)
    #   2. if invalid: REPAIR with the prior errors + prior raw text and
    #      a lower temperature (deterministic-leaning) so the model can
    #      correct the structural mistake.
    #   3. if still invalid: a second sample with a different seed.
    # Every attempt is recorded in raw_doc.attempts so the audit shows
    # exactly what the model did at each step.

    REPAIR_PROMPT_HEADER = (
        "Your previous output failed validation. Fix it and return only the\n"
        "corrected output (matching the format the original prompt requested).\n"
        "Do not add explanation. Do not include the prior errors in the output.\n\n"
        "Errors:\n{errors}\n\n"
        "Previous output:\n{previous_output}\n\n"
        "ORIGINAL PROMPT:\n{original_prompt}\n"
    )

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
        # Per-attempt audit trail recorded in raw_doc.attempts (Phase C.5).
        attempt_log: list[dict[str, Any]] = []
        validation: ValidationResult = ValidationResult(passed=False)
        last_error: str | None = None

        attempt_plan: tuple[tuple[str, int, float, bool], ...] = (
            # (kind, seed_offset, temperature, do_sample)
            ("sample",  0, self.temperature, self.do_sample),
            ("repair",  1, 0.35,             True),
            ("sample",  2, self.temperature, True),
        )

        for attempt_idx, (kind, seed_offset, temp, do_sample) in enumerate(attempt_plan, start=1):
            if kind == "repair":
                if not attempt_log or attempt_log[-1].get("validation", {}).get("passed"):
                    # Nothing to repair; stop.
                    break
                last = attempt_log[-1]
                errors_str = last.get("validation", {}).get("errors_str", "unknown errors")
                previous_output = last.get("raw_text", "")[:1500]
                repair_prompt = self.REPAIR_PROMPT_HEADER.format(
                    errors=errors_str,
                    previous_output=previous_output,
                    original_prompt=prompt,
                )
                req_prompt = repair_prompt
            else:
                if attempt_idx > 1 and attempt_log and attempt_log[-1].get("validation", {}).get("passed"):
                    break
                req_prompt = prompt

            req = GenerationRequest(
                prompt=req_prompt,
                max_new_tokens=self.max_new_tokens,
                temperature=temp,
                top_p=self.top_p,
                do_sample=do_sample,
                seed=seed + seed_offset,
            )

            audit.emit(
                "slot_model_called",
                slot=self.slot_address,
                attempt=attempt_idx,
                prompt_hash=prompt_hash,
                data={"attempt_kind": kind},
            )

            entry: dict[str, Any] = {
                "kind": kind,
                "attempt": attempt_idx,
                "temperature": temp,
                "do_sample": do_sample,
                "seed": seed + seed_offset,
            }

            try:
                resp = await manager.generate(req)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                entry["error"] = last_error
                entry["validation"] = {"passed": False, "errors_str": last_error}
                attempt_log.append(entry)
                audit.emit(
                    "slot_model_failed",
                    slot=self.slot_address,
                    attempt=attempt_idx,
                    error_code="MODEL_CALL_FAILED",
                    error_detail=last_error,
                )
                continue

            audit.emit(
                "slot_model_returned",
                slot=self.slot_address,
                attempt=attempt_idx,
                latency_ms=resp.latency_ms,
            )
            entry["raw_text"] = resp.text
            entry["latency_ms"] = resp.latency_ms

            try:
                selected = self.parse_selected(resp.text)
            except Exception as exc:
                last_error = f"PARSE_ERROR: {exc}"
                entry["error"] = last_error
                entry["validation"] = {"passed": False, "errors_str": last_error}
                attempt_log.append(entry)
                audit.emit(
                    "slot_validation_failed",
                    slot=self.slot_address,
                    attempt=attempt_idx,
                    error_code="OUTPUT_UNPARSEABLE",
                    error_detail=last_error,
                )
                continue

            candidates.append(selected)
            entry["parsed"] = selected if not isinstance(selected, str) else None
            attempt_validation = self.validator.validate(selected)
            entry["validation"] = {
                "passed": attempt_validation.passed,
                "errors": [e.as_dict() for e in attempt_validation.errors],
                "errors_str": "; ".join(e.detail for e in attempt_validation.errors),
            }
            attempt_log.append(entry)

            validation = attempt_validation

            if attempt_validation.passed:
                audit.emit("slot_validation_passed", slot=self.slot_address, attempt=attempt_idx)
                break

            audit.emit(
                "slot_validation_failed",
                slot=self.slot_address,
                attempt=attempt_idx,
                error_code=attempt_validation.errors[0].code if attempt_validation.errors else "VALIDATION_FAILED",
                error_detail="; ".join(e.detail for e in attempt_validation.errors),
            )

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
            "attempts":   attempt_log,
            "attempts_count": len(attempt_log),
            "validation": validation.as_dict(),
            "latency_ms": latency_ms,
        }
        raw_path.write_text(json.dumps(raw_doc, indent=2, ensure_ascii=False, default=str))

        succeeded = validation.passed
        audit.emit(
            "slot_completed",
            slot=self.slot_address,
            attempt=len(attempt_log),
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
            attempts=len(attempt_log),
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
