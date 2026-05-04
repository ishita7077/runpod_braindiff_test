"""Headline validator (Slot 1).

Rules:
  * exactly 2 sentences
  * each sentence ≤ 8 words
  * no anatomical terms (insula, cortex, prefrontal, mPFC, dlPFC, etc.)
  * banned-pattern check (winner/loser, %, r=, citations, years)
  * no surrounding quotes
"""

from __future__ import annotations

import re

from .base import BaseValidator, ValidationError, ValidationResult


_ANATOMICAL_TERMS = re.compile(
    r"\b(insula|cortex|cortical|prefrontal|amygdala|hippocampus|cingulate|"
    r"mpfc|dlpfc|vlpfc|tpj|fef|ips|broca|wernicke|fusiform|parietal|frontal|"
    r"temporal|occipital|hemisphere|medial|lateral|dorsal|ventral|anterior|posterior)\b",
    re.IGNORECASE,
)


class HeadlineValidator(BaseValidator):
    slot = "headline"

    def validate(self, output: str) -> ValidationResult:
        errors: list[ValidationError] = []

        if not isinstance(output, str) or not output.strip():
            return ValidationResult(passed=False, errors=[ValidationError(code="EMPTY_OUTPUT", detail="headline is empty")])

        text = output.strip()

        # Strip surrounding quotes if present, but flag.
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
            errors.append(ValidationError(code="WRAPPED_IN_QUOTES", detail="remove surrounding quotes"))
            text = text[1:-1].strip()

        # Sentence count.
        n_sentences = self.count_sentences(text)
        if n_sentences != 2:
            errors.append(ValidationError(
                code="WRONG_SENTENCE_COUNT",
                detail=f"expected exactly 2 sentences, got {n_sentences}",
            ))

        # Per-sentence word limit.
        sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
        for i, sent in enumerate(sentences):
            wc = self.count_words(sent)
            if wc > 8:
                errors.append(ValidationError(
                    code="SENTENCE_OVER_8_WORDS",
                    detail=f"sentence #{i+1} has {wc} words: {sent!r}",
                ))

        # Anatomical terms.
        anat = _ANATOMICAL_TERMS.search(text)
        if anat:
            errors.append(ValidationError(
                code="ANATOMICAL_TERM",
                detail=f"headline contains anatomical term {anat.group(0)!r} — keep plain English",
            ))

        # Banned patterns (numbers, citations, winner/loser).
        errors.extend(self.check_banned_patterns(text))

        return ValidationResult(passed=not errors, errors=errors)
