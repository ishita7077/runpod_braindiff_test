"""Recipe match slot — deterministic library_matcher + LLM rationale only.

This slot is special: the library_id, name, confidence, score_breakdown all
come from library_matcher.match_recipe (deterministic). The LLM only writes
the one-sentence rationale, scoped to that match.

The selected value is the full assembled object so content.json gets
{library_id, name, confidence, score_breakdown, rationale, built_for_tag}.

Two instances are constructed (video_a and video_b) — each runs independently.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..lib.audit_log import AuditLogger
from ..lib.ids import deterministic_seed, hash_string, now_iso
from ..lib.input_normalizer import CANONICAL_SYSTEMS, NormalizedInputs
from ..lib.library_matcher import MatchResult, match_recipe
from ..lib.model_manager import GenerationRequest, ModelManager
from ..validators.recipe_match import RecipeMatchValidator
from .base import Slot, SlotResult


class RecipeMatchSlot(Slot):
    """One per video. slot_address = recipe_match.video_a or recipe_match.video_b."""

    template_name = "recipe_match_rationale.txt"
    max_new_tokens = 100
    output_is_json = False  # the rationale is text; we wrap it into JSON ourselves

    def __init__(self, *, video_key: str) -> None:
        if video_key not in ("video_a", "video_b"):
            raise ValueError(f"video_key must be video_a or video_b, got {video_key}")
        self.video_key = video_key
        self.slot_address = f"recipe_match.{video_key}"
        super().__init__(validator=RecipeMatchValidator())

    def build_template_context(self, inputs: NormalizedInputs, *, match: MatchResult) -> dict[str, Any]:
        video = getattr(inputs, self.video_key)
        breakdown_lines = "\n".join(f"  - {k}: {v:.2f}" for k, v in match.score_breakdown.items())

        # Top 2 features that drove the match: highest two breakdown components.
        sorted_features = sorted(match.score_breakdown.items(), key=lambda kv: kv[1], reverse=True)[:2]
        top_features = "\n".join(
            f"  - {k} score {v:.2f} — {self._feature_evidence(k, video)}"
            for k, v in sorted_features
        )

        return {
            "recipe_name":           match.name,
            "library_id":            match.library_id,
            "confidence":            f"{match.confidence:.2f}",
            "score_breakdown_formatted": breakdown_lines,
            "top_features":          top_features,
            "video_display_name":    video.display_name,
        }

    @staticmethod
    def _feature_evidence(component: str, video: Any) -> str:
        """One short fragment summarising what the video shows for this component."""
        if component == "system_means":
            highest = max(video.system_means.items(), key=lambda kv: kv[1])
            return f"{highest[0]} mean = {highest[1]:.2f}"
        if component == "chords":
            ids = [ev.chord_id for ev in video.chord_events]
            return f"detected chords = {ids}"
        if component == "timing":
            times = [ev.timestamp_seconds for ev in video.chord_events]
            return f"chord times = {times}"
        if component == "integration":
            return f"integration_score = {video.integration_score:.2f}"
        if component == "hub":
            return f"hub_node = {video.hub_node}"
        return ""

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
        """Override base.run — first do deterministic match, then LLM for rationale."""
        import json
        audit.emit("slot_started", slot=self.slot_address)
        start = time.perf_counter()

        video = getattr(inputs, self.video_key)
        match = match_recipe(video)

        # Audit the deterministic score, all entries logged for forensics.
        audit.emit(
            "library_match_scored",
            slot=self.slot_address,
            data={
                "winning_library_id": match.library_id,
                "confidence":         match.confidence,
                "score_breakdown":    match.score_breakdown,
                "all_scores":         [{"id": s.library_id, "score": s.score} for s in match.all_scores[:5]],
            },
        )

        if match.library_id == "uncategorized":
            audit.emit(
                "library_match_low_confidence",
                slot=self.slot_address,
                error_code="MATCH_BELOW_THRESHOLD",
                error_detail=f"top score {match.confidence:.2f} < 0.6",
                data={"closest_id": match.closest_entry_if_uncategorized.library_id if match.closest_entry_if_uncategorized else None},
            )

        # Render rationale prompt. Uses the deterministic match as input.
        ctx = self.build_template_context(inputs, match=match)
        prompt = self.render_prompt(ctx)
        prompt_hash = hash_string(prompt)
        audit.emit("slot_prompt_rendered", slot=self.slot_address, prompt_hash=prompt_hash)

        seed = deterministic_seed(comparison_id, self.slot_address)
        rationale = match.description_template[:140].strip() if match.description_template else "Closest match by library scoring."  # default
        candidates: list[str] = []
        from ..validators.base import ValidationResult
        validation: ValidationResult = ValidationResult(passed=True)
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

            candidate_rationale = resp.text.strip().strip('"').strip("'")
            candidates.append(candidate_rationale)

            # Build the assembled object that the validator checks.
            assembled = {
                "library_id":      match.library_id,
                "name":            match.name,
                "built_for_tag":   match.built_for_tag,
                "confidence":      match.confidence,
                "score_breakdown": match.score_breakdown,
                "rationale":       candidate_rationale,
            }
            validation = self.validator.validate(assembled)
            if validation.passed:
                rationale = candidate_rationale
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

        # Final assembled value — uses last validated rationale OR the default if both attempts failed.
        # Even when LLM rationale fails, the deterministic match is still good — emit ok with template fallback.
        final = {
            "library_id":      match.library_id,
            "name":            match.name,
            "built_for_tag":   match.built_for_tag,
            "confidence":      match.confidence,
            "score_breakdown": match.score_breakdown,
            "rationale":       rationale,
        }
        succeeded = True  # match itself is always valid; rationale falls back to template

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
            "selected":        final,
            "attempts":        attempts,
            "validation":      validation.as_dict() if validation else {"passed": True, "errors": []},
            "latency_ms":      latency_ms,
            "deterministic_match": {
                "library_id":      match.library_id,
                "confidence":      match.confidence,
                "score_breakdown": match.score_breakdown,
            },
        }
        raw_path.write_text(json.dumps(raw_doc, indent=2, ensure_ascii=False))
        audit.emit(
            "slot_completed", slot=self.slot_address,
            attempt=attempts, latency_ms=latency_ms,
            raw_output_path=str(raw_path),
        )
        return SlotResult(
            slot_address=self.slot_address,
            selected=final,
            candidates=candidates,
            validation=validation,
            raw_path=raw_path,
            attempts=attempts,
            latency_ms=latency_ms,
            succeeded=succeeded,
        )
