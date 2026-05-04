"""Frame 02 sub-paragraph validator (Slot 7)."""

from __future__ import annotations

from .base import BaseValidator, ValidationError, ValidationResult


class Frame2SubValidator(BaseValidator):
    slot = "frame2_sub"

    def __init__(self, *, required_recipe_names: list[str]) -> None:
        # Both recipe names should appear so the sub explicitly distinguishes them.
        self.required_recipe_names = [n for n in required_recipe_names if n]

    def validate(self, output: str) -> ValidationResult:
        errors: list[ValidationError] = []
        if not isinstance(output, str) or not output.strip():
            return ValidationResult(passed=False, errors=[
                ValidationError(code="EMPTY_OUTPUT", detail="frame2_sub is empty"),
            ])

        text = output.strip()

        n = self.count_sentences(text)
        if not (2 <= n <= 4):
            errors.append(ValidationError(
                code="WRONG_SENTENCE_COUNT",
                detail=f"frame2_sub should be 2-4 sentences, got {n}",
            ))

        wc = self.count_words(text)
        if wc > 50:
            errors.append(ValidationError(
                code="OVER_WORD_LIMIT",
                detail=f"frame2_sub has {wc} words, max 50",
            ))

        text_lower = text.lower()
        missing = [n for n in self.required_recipe_names if n.lower() not in text_lower]
        if missing:
            errors.append(ValidationError(
                code="MISSING_RECIPE_NAME",
                detail=f"frame2_sub must mention recipe(s): {missing}",
            ))

        # Must define "chord" — accept any sentence containing the word "chord".
        if "chord" not in text_lower:
            errors.append(ValidationError(
                code="MISSING_CHORD_DEFINITION",
                detail="frame2_sub must define what a 'chord' is",
            ))

        errors.extend(self.check_banned_patterns(text))
        return ValidationResult(passed=not errors, errors=errors)
