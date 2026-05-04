"""Base classes for slot validators.

Each slot has its own validator subclassing BaseValidator. validate() returns
a ValidationResult with structured errors using the same enum codes as
raw_slot.schema.json -> validation.errors[].code.

Validators are pure: same input -> same result. No I/O, no side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .banned_patterns import find_banned_patterns


@dataclass
class ValidationError:
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


@dataclass
class ValidationResult:
    passed: bool
    errors: list[ValidationError] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": [e.as_dict() for e in self.errors],
        }


class BaseValidator:
    """Subclass and override validate(). Provides reusable helpers."""

    slot: str = "base"

    def validate(self, output: Any) -> ValidationResult:  # pragma: no cover
        raise NotImplementedError

    # ------- helpers shared by text slot validators -------

    @staticmethod
    def count_sentences(text: str) -> int:
        """Approximate sentence count. Splits on . ! ? and ignores trailing whitespace
        AND ignores chunks that don't contain at least one letter (so trailing
        markdown bits like a lone '*' don't count as a sentence).
        """
        import re
        chunks = [
            c.strip() for c in re.split(r"[.!?]+", text)
            if c.strip() and any(ch.isalpha() for ch in c)
        ]
        return len(chunks)

    @staticmethod
    def count_words(text: str) -> int:
        return len([w for w in text.split() if w.strip()])

    @staticmethod
    def check_banned_patterns(text: str) -> list[ValidationError]:
        return [
            ValidationError(code="BANNED_PATTERN", detail=f"{hit.code}: {hit.detail} matched={hit.matched_text!r}")
            for hit in find_banned_patterns(text)
        ]
