"""Chord context validator (Slot 5).

Rules:
  * 1 sentence
  * ≤ 22 words
  * must reference one specific input (quote substring, timestamp, creator name,
    or a specific cortical detail) — checked by passing required_substrings to
    the validator at construction time
  * banned patterns
"""

from __future__ import annotations

from .base import BaseValidator, ValidationError, ValidationResult


class ChordContextValidator(BaseValidator):
    slot = "chord_context"

    def __init__(self, *, required_any_of: list[str] | None = None) -> None:
        # The slot supplies hints (timestamp string, creator name, quote words).
        # At least one must appear in the output for grounding.
        self.required_any_of = [s for s in (required_any_of or []) if s]

    def validate(self, output: str) -> ValidationResult:
        errors: list[ValidationError] = []

        if not isinstance(output, str) or not output.strip():
            return ValidationResult(passed=False, errors=[
                ValidationError(code="EMPTY_OUTPUT", detail="chord_context is empty"),
            ])

        text = output.strip()

        n = self.count_sentences(text)
        if n != 1:
            errors.append(ValidationError(
                code="WRONG_SENTENCE_COUNT",
                detail=f"chord_context must be 1 sentence, got {n}",
            ))

        wc = self.count_words(text)
        if wc > 22:
            errors.append(ValidationError(
                code="OVER_WORD_LIMIT",
                detail=f"chord_context has {wc} words, max 22",
            ))

        if self.required_any_of:
            text_lower = text.lower()
            if not any(hint.lower() in text_lower for hint in self.required_any_of):
                errors.append(ValidationError(
                    code="MISSING_GROUNDING",
                    detail=f"chord_context must reference one of: {self.required_any_of!r}",
                ))

        errors.extend(self.check_banned_patterns(text))
        return ValidationResult(passed=not errors, errors=errors)
