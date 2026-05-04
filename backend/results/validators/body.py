"""Body paragraph validator (Slot 2)."""

from __future__ import annotations

from .base import BaseValidator, ValidationError, ValidationResult


class BodyValidator(BaseValidator):
    slot = "body"

    def validate(self, output: str) -> ValidationResult:
        errors: list[ValidationError] = []
        if not isinstance(output, str) or not output.strip():
            return ValidationResult(passed=False, errors=[
                ValidationError(code="EMPTY_OUTPUT", detail="body is empty"),
            ])

        text = output.strip()
        n = self.count_sentences(text)
        if not (2 <= n <= 4):
            errors.append(ValidationError(
                code="WRONG_SENTENCE_COUNT",
                detail=f"body should be 2-4 sentences, got {n}",
            ))

        wc = self.count_words(text)
        if wc > 90:
            errors.append(ValidationError(
                code="OVER_WORD_LIMIT",
                detail=f"body has {wc} words, max 90",
            ))

        errors.extend(self.check_banned_patterns(text))
        return ValidationResult(passed=not errors, errors=errors)
