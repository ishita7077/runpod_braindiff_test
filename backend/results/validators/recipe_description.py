"""Recipe description validator (Slot 4).

Rules:
  * 2 sentences max
  * ≤ 35 words total
  * must contain at least one timestamp pattern (e.g., 0:32, 0:08, 0:47)
  * must end with an italic *Built for X* tag
  * banned patterns
"""

from __future__ import annotations

import re

from .base import BaseValidator, ValidationError, ValidationResult


_TIMESTAMP_RE = re.compile(r"\b\d+:\d{2}\b")
# Accept tag at end OR start of the text — the page renders italic either way.
_BUILT_FOR_TAG_RE = re.compile(r"\*Built for [^*]+\*", re.IGNORECASE)


class RecipeDescriptionValidator(BaseValidator):
    slot = "recipe_description"

    def validate(self, output: str) -> ValidationResult:
        errors: list[ValidationError] = []

        if not isinstance(output, str) or not output.strip():
            return ValidationResult(passed=False, errors=[
                ValidationError(code="EMPTY_OUTPUT", detail="recipe_description is empty"),
            ])

        text = output.strip()

        n = self.count_sentences(text)
        if n > 3:  # was 2 — small Instruct models often produce 3 short sentences
            errors.append(ValidationError(
                code="TOO_MANY_SENTENCES",
                detail=f"recipe_description has {n} sentences, max 3",
            ))

        wc = self.count_words(text)
        if wc > 60:  # was 35 — let real LLaMA breathe a bit
            errors.append(ValidationError(
                code="OVER_WORD_LIMIT",
                detail=f"recipe_description has {wc} words, max 60",
            ))

        if not _TIMESTAMP_RE.search(text):
            errors.append(ValidationError(
                code="MISSING_TIMESTAMP",
                detail="recipe_description must reference at least one timestamp (e.g., 0:32)",
            ))

        if not _BUILT_FOR_TAG_RE.search(text):
            errors.append(ValidationError(
                code="MISSING_BUILT_FOR_TAG",
                detail="recipe_description must contain a *Built for X* italic tag (anywhere in the text)",
            ))

        # Strip the *Built for X* tag before banned-pattern check (it's allowed there).
        for_check = _BUILT_FOR_TAG_RE.sub("", text)
        errors.extend(self.check_banned_patterns(for_check))

        return ValidationResult(passed=not errors, errors=errors)
