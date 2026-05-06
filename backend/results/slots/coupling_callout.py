"""Coupling callout slot — one per (video, coupling_type) pair.

For each video we surface 3 couplings:
  * strongest — highest positive r
  * weakest   — smallest |r|
  * anti      — most negative r (only meaningful if min(r) < 0)

If the video has no negative couplings, the anti slot returns its template
fallback rather than fabricating one — the audit log records why.
"""

from __future__ import annotations

import time
import json
from pathlib import Path
from typing import Any

from ..lib.audit_log import AuditLogger
from ..lib.ids import deterministic_seed, hash_string, now_iso
from ..lib.input_normalizer import CouplingEntry, NormalizedInputs
from ..lib.library_matcher import match_recipe
from ..lib.model_manager import GenerationRequest, ModelManager
from ..validators.coupling_callout import CouplingCalloutValidator
from ..validators.base import ValidationResult
from .base import Slot, SlotResult, voice_exemplars


_DESCRIPTOR = {
    "strongest": "tightly coupled",
    "weakest":   "decoupled",
    "anti":      "anti-coupled",
}


def _pick_pair(couplings: list[CouplingEntry], coupling_type: str) -> CouplingEntry | None:
    if not couplings:
        return None
    if coupling_type == "strongest":
        return max(couplings, key=lambda c: c.r)
    if coupling_type == "weakest":
        return min(couplings, key=lambda c: abs(c.r))
    if coupling_type == "anti":
        most_neg = min(couplings, key=lambda c: c.r)
        return most_neg if most_neg.r < 0 else None
    return None


class CouplingCalloutSlot(Slot):
    template_name = "coupling_callout.txt"
    max_new_tokens = 110

    def __init__(self, *, video_key: str, coupling_type: str) -> None:
        if video_key not in ("video_a", "video_b"):
            raise ValueError(f"video_key invalid: {video_key}")
        if coupling_type not in ("strongest", "weakest", "anti"):
            raise ValueError(f"coupling_type invalid: {coupling_type}")
        self.video_key = video_key
        self.coupling_type = coupling_type
        self.slot_address = f"coupling_callouts.{video_key}.{coupling_type}"

        # Pair is unknown until run() — validator system_a/b set per-run via _validator_for_pair.
        super().__init__(validator=CouplingCalloutValidator(system_a="", system_b=""))

    def _validator_for_pair(self, pair: CouplingEntry) -> CouplingCalloutValidator:
        return CouplingCalloutValidator(system_a=pair.system_a, system_b=pair.system_b)

    def build_template_context(self, inputs: NormalizedInputs, *, pair: CouplingEntry) -> dict[str, Any]:
        video = getattr(inputs, self.video_key)
        match = match_recipe(video)
        exemplars = voice_exemplars().get("coupling_callout", [])
        exemplar_block = "\n".join(f"  {i+1}. {e}" for i, e in enumerate(exemplars[:4]))

        # Phase C.4: r_value removed from the rendered prompt — it was
        # contradicting the banned-pattern validator (no numeric values).
        # The pair's r still influences the descriptor (strongest/weakest/anti).
        return {
            "video_display_name": video.display_name,
            "coupling_type":      self.coupling_type,
            "system_a":           pair.system_a,
            "system_b":           pair.system_b,
            "descriptor":         _DESCRIPTOR[self.coupling_type],
            "recipe_name":        match.name,
            "exemplars":          exemplar_block,
        }

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

        video = getattr(inputs, self.video_key)
        pair = _pick_pair(video.couplings, self.coupling_type)
        if pair is None:
            # Nothing to write — emit fallback marker, assembler will use default.
            audit.emit(
                "slot_completed",
                slot=self.slot_address,
                error_code="NO_PAIR_AVAILABLE",
                error_detail=f"video {self.video_key} has no {self.coupling_type} coupling to write",
            )
            return SlotResult(
                slot_address=self.slot_address,
                selected=None,
                candidates=[],
                validation=ValidationResult(passed=False),
                raw_path=None,
                attempts=0,
                latency_ms=int((time.perf_counter() - start) * 1000),
                succeeded=False,
            )

        # Re-bind validator for this pair.
        self.validator = self._validator_for_pair(pair)

        ctx = self.build_template_context(inputs, pair=pair)
        prompt = self.render_prompt(ctx)
        prompt_hash = hash_string(prompt)
        audit.emit("slot_prompt_rendered", slot=self.slot_address, prompt_hash=prompt_hash)

        seed = deterministic_seed(comparison_id, self.slot_address)
        candidates: list[str] = []
        validation = ValidationResult(passed=False)
        attempts = 0

        for attempt in (1, 2):
            attempts = attempt
            req = GenerationRequest(
                prompt=prompt,
                max_new_tokens=self.max_new_tokens,
                temperature=0.4 if attempt == 1 else 0.5,
                top_p=0.9,
                do_sample=False if attempt == 1 else True,
                seed=seed + (attempt - 1),
            )
            audit.emit("slot_model_called", slot=self.slot_address, attempt=attempt, prompt_hash=prompt_hash)
            try:
                resp = await manager.generate(req)
            except Exception as exc:
                audit.emit("slot_model_failed", slot=self.slot_address, attempt=attempt,
                           error_code="MODEL_CALL_FAILED", error_detail=f"{type(exc).__name__}: {exc}")
                if attempt == 2: break
                audit.emit("slot_retry_started", slot=self.slot_address, attempt=2)
                continue
            audit.emit("slot_model_returned", slot=self.slot_address, attempt=attempt, latency_ms=resp.latency_ms)

            text = resp.text.strip().strip('"').strip("'")
            candidates.append(text)
            validation = self.validator.validate(text)
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
        succeeded = validation.passed

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
                "do_sample":      False,
                "temperature":    0.4,
                "top_p":          0.9,
                "max_new_tokens": self.max_new_tokens,
            },
            "prompt_rendered": prompt,
            "candidates":      candidates,
            "selected":        candidates[-1] if (candidates and validation.passed) else None,
            "attempts":        attempts,
            "validation":      validation.as_dict(),
            "latency_ms":      latency_ms,
            "pair": {"system_a": pair.system_a, "system_b": pair.system_b, "r": pair.r},
        }
        raw_path.write_text(json.dumps(raw_doc, indent=2, ensure_ascii=False))

        audit.emit(
            "slot_completed", slot=self.slot_address,
            attempt=attempts, latency_ms=latency_ms,
            raw_output_path=str(raw_path),
            error_code=None if succeeded else "VALIDATION_FAILED_FINAL",
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
