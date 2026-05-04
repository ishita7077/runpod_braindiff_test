"""Coupling callout validator (Slot 6)."""

from __future__ import annotations

from .base import BaseValidator, ValidationError, ValidationResult


# Display names of the canonical systems (rough English forms the LLM is told to use).
_SYSTEM_DISPLAY: dict[str, list[str]] = {
    "personal_resonance": ["personal", "self-relevance", "resonance"],
    "attention":          ["attention"],
    "brain_effort":       ["effort", "control", "cognitive control"],
    "gut_reaction":       ["gut", "visceral", "body"],
    "memory_encoding":    ["memory"],
    "social_thinking":    ["social", "theory-of-mind", "mentalising"],
    "language_depth":     ["language"],
}


class CouplingCalloutValidator(BaseValidator):
    slot = "coupling_callout"

    def __init__(self, *, system_a: str, system_b: str) -> None:
        self.system_a = system_a
        self.system_b = system_b

    def validate(self, output: str) -> ValidationResult:
        errors: list[ValidationError] = []
        if not isinstance(output, str) or not output.strip():
            return ValidationResult(passed=False, errors=[
                ValidationError(code="EMPTY_OUTPUT", detail="coupling_callout is empty"),
            ])

        text = output.strip()

        n = self.count_sentences(text)
        if n != 2:
            errors.append(ValidationError(
                code="WRONG_SENTENCE_COUNT",
                detail=f"coupling_callout must be exactly 2 sentences, got {n}",
            ))

        wc = self.count_words(text)
        if wc > 38:
            errors.append(ValidationError(
                code="OVER_WORD_LIMIT",
                detail=f"coupling_callout has {wc} words, max 38",
            ))

        text_lower = text.lower()
        for sys_key in (self.system_a, self.system_b):
            display_forms = _SYSTEM_DISPLAY.get(sys_key, [sys_key.split("_")[0]])
            if not any(form in text_lower for form in display_forms):
                errors.append(ValidationError(
                    code="MISSING_SYSTEM_NAME",
                    detail=f"coupling_callout must reference system {sys_key!r} (any of {display_forms})",
                ))

        errors.extend(self.check_banned_patterns(text))
        return ValidationResult(passed=not errors, errors=errors)
