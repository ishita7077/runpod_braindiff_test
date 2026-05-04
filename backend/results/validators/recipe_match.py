"""Recipe match validator.

The match itself is deterministic (library_matcher.py). The LLM only writes
the rationale. Validator checks the assembled object's shape + the rationale
text.
"""

from __future__ import annotations

from typing import Any

from .base import BaseValidator, ValidationError, ValidationResult


class RecipeMatchValidator(BaseValidator):
    slot = "recipe_match"

    def validate(self, output: Any) -> ValidationResult:
        errors: list[ValidationError] = []

        if not isinstance(output, dict):
            return ValidationResult(passed=False, errors=[
                ValidationError(code="INVALID_JSON", detail="recipe_match.value must be an object"),
            ])

        for required in ("library_id", "name", "confidence", "rationale"):
            if required not in output:
                errors.append(ValidationError(
                    code="MISSING_REQUIRED_FIELD",
                    detail=f"recipe_match missing field {required!r}",
                ))

        if "confidence" in output:
            try:
                c = float(output["confidence"])
                if not (0.0 <= c <= 1.0):
                    errors.append(ValidationError(
                        code="CONFIDENCE_OUT_OF_RANGE",
                        detail=f"confidence={c} not in [0,1]",
                    ))
            except (TypeError, ValueError):
                errors.append(ValidationError(
                    code="CONFIDENCE_NOT_NUMERIC",
                    detail=f"confidence={output['confidence']!r}",
                ))

        if "rationale" in output and isinstance(output["rationale"], str):
            errors.extend(self.check_banned_patterns(output["rationale"]))
            wc = self.count_words(output["rationale"])
            if wc > 35:
                errors.append(ValidationError(
                    code="RATIONALE_OVER_WORD_LIMIT",
                    detail=f"rationale has {wc} words, max 35",
                ))

        return ValidationResult(passed=not errors, errors=errors)
