"""Validator for the analysis_brief slot — Phase C.3 / C.6.

Checks structural shape and grounding:
  * Top-level dict with the required keys + correct types
  * thesis / tradeoff / limitations are non-empty strings
  * why_it_happened: list[dict{claim, evidence_refs}], evidence_refs non-empty
  * recommendations: list[dict{action, because, evidence_refs}], 1-3 items,
    every recommendation must have at least one evidence_ref, NONE may use
    a banned generic phrase
  * confidence in {"low", "medium", "high"}
  * (when valid_evidence_refs is supplied) every evidence_ref must be
    present in that set — Phase C.6 grounding
"""

from __future__ import annotations

from typing import Any

from .base import BaseValidator, ValidationError, ValidationResult


_BANNED_GENERIC_PHRASES: tuple[str, ...] = (
    # Plan §6 calls these out explicitly.
    "make it more engaging",
    "improve clarity",
    "optimize content",
    "consider audience needs",
    # A few more in the same family.
    "boost engagement",
    "enhance clarity",
    "improve engagement",
    "increase engagement",
    "drive clicks",
    "best practices",
    "leverage",
    "synergy",
)


def _contains_banned_phrase(text: str) -> str | None:
    low = text.lower()
    for phrase in _BANNED_GENERIC_PHRASES:
        if phrase in low:
            return phrase
    return None


class AnalysisBriefValidator(BaseValidator):
    slot = "analysis_brief"

    def __init__(self, *, valid_evidence_refs: set[str] | None = None) -> None:
        # If supplied, every evidence_ref produced by the model is checked
        # against this set. None disables grounding (used for unit tests of
        # structural validation only).
        self.valid_evidence_refs = valid_evidence_refs

    def validate(self, output: Any) -> ValidationResult:
        errors: list[ValidationError] = []

        if not isinstance(output, dict):
            return ValidationResult(passed=False, errors=[
                ValidationError(code="OUTPUT_UNPARSEABLE", detail=f"expected dict, got {type(output).__name__}")
            ])

        for key in ("thesis", "tradeoff", "limitations"):
            v = output.get(key)
            if not isinstance(v, str) or not v.strip():
                errors.append(ValidationError(code="MISSING_FIELD", detail=f"{key} must be a non-empty string"))

        # confidence
        conf = output.get("confidence")
        if conf not in ("low", "medium", "high"):
            errors.append(ValidationError(code="MISSING_FIELD", detail="confidence must be one of low|medium|high"))

        # why_it_happened
        why = output.get("why_it_happened")
        if not isinstance(why, list) or not why:
            errors.append(ValidationError(code="MISSING_FIELD", detail="why_it_happened must be a non-empty list"))
        else:
            for i, item in enumerate(why):
                if not isinstance(item, dict):
                    errors.append(ValidationError(code="WHY_ITEM_TYPE", detail=f"why_it_happened[{i}] not a dict"))
                    continue
                claim = item.get("claim")
                if not isinstance(claim, str) or not claim.strip():
                    errors.append(ValidationError(code="WHY_ITEM_CLAIM", detail=f"why_it_happened[{i}].claim missing"))
                refs = item.get("evidence_refs")
                if not isinstance(refs, list) or not refs:
                    errors.append(ValidationError(code="WHY_ITEM_REFS", detail=f"why_it_happened[{i}].evidence_refs must be a non-empty list"))

        # recommendations
        recs = output.get("recommendations")
        if not isinstance(recs, list) or not (1 <= len(recs) <= 3):
            errors.append(ValidationError(code="MISSING_FIELD", detail="recommendations must be a list of 1-3 items"))
        else:
            for i, rec in enumerate(recs):
                if not isinstance(rec, dict):
                    errors.append(ValidationError(code="REC_ITEM_TYPE", detail=f"recommendations[{i}] not a dict"))
                    continue
                for k in ("action", "because"):
                    v = rec.get(k)
                    if not isinstance(v, str) or not v.strip():
                        errors.append(ValidationError(code="REC_ITEM_FIELD", detail=f"recommendations[{i}].{k} missing"))
                        continue
                    banned = _contains_banned_phrase(v)
                    if banned:
                        errors.append(ValidationError(
                            code="REC_GENERIC_PHRASE",
                            detail=f"recommendations[{i}].{k} contains banned phrase {banned!r}",
                        ))
                refs = rec.get("evidence_refs")
                if not isinstance(refs, list) or not refs:
                    errors.append(ValidationError(
                        code="REC_NO_EVIDENCE",
                        detail=f"recommendations[{i}].evidence_refs must be a non-empty list",
                    ))

        # Grounding: every evidence_ref must come from the packet.
        if self.valid_evidence_refs is not None:
            for section_key in ("why_it_happened", "recommendations"):
                section = output.get(section_key) or []
                if not isinstance(section, list):
                    continue
                for i, item in enumerate(section):
                    if not isinstance(item, dict):
                        continue
                    refs = item.get("evidence_refs") or []
                    if not isinstance(refs, list):
                        continue
                    for ref in refs:
                        if ref not in self.valid_evidence_refs:
                            errors.append(ValidationError(
                                code="UNGROUNDED_EVIDENCE_REF",
                                detail=f"{section_key}[{i}] cites {ref!r} which is not in the evidence packet",
                            ))

        return ValidationResult(passed=not errors, errors=errors)
