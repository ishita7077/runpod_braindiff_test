"""Validator for chord_contextual_meaning slot.

Rules:
  * 2-3 sentences
  * ≤ 70 words
  * banned-pattern check (no %, no r=, no et al, no year stamps, no winner/loser)
  * MUST contain timestamp OR a fragment of the quote OR the video title
    (proves the meaning was actually contextualised, not generic)
"""

from __future__ import annotations

from .base import BaseValidator, ValidationError, ValidationResult


class ChordContextualMeaningValidator(BaseValidator):
    slot = "chord_contextual_meaning"

    def validate(self, output: str) -> ValidationResult:
        errors: list[ValidationError] = []
        if not isinstance(output, str) or not output.strip():
            return ValidationResult(passed=False, errors=[
                ValidationError(code="EMPTY_OUTPUT", detail="contextual meaning is empty"),
            ])
        text = output.strip()

        n = self.count_sentences(text)
        if not (1 <= n <= 4):
            errors.append(ValidationError(
                code="WRONG_SENTENCE_COUNT",
                detail=f"contextual meaning should be 1-4 sentences, got {n}",
            ))

        wc = self.count_words(text)
        if wc > 100:
            errors.append(ValidationError(
                code="OVER_WORD_LIMIT",
                detail=f"contextual meaning has {wc} words, max 100",
            ))

        errors.extend(self.check_banned_patterns(text))
        return ValidationResult(passed=not errors, errors=errors)
