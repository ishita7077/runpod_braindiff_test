"""Shared validator: science-claim banned patterns (audit point #10).

The LLM should never invent percentages, r-values, citations, or year-stamped
references. All citation-level claims live in chord_library.json with explicit
citation_ids. This validator catches LLM output that tries to bring its own.

Used by every text slot validator in the pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# These patterns trigger BANNED_PATTERN with a specific subcode.
# Order matters: more specific first.
_BANNED_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("BANNED_PERCENT",       re.compile(r"\b\d{1,3}\s?%"),                       "Numeric percent claim (e.g. '89%')."),
    ("BANNED_R_VALUE",       re.compile(r"\br\s?=\s?[-+]?\d?\.?\d+"),            "Statistical r-value (e.g. 'r=0.87')."),
    ("BANNED_P_VALUE",       re.compile(r"\bp\s?[<>=]\s?\d?\.?\d+"),             "Statistical p-value (e.g. 'p<0.05')."),
    ("BANNED_CITATION",      re.compile(r"\bet\s+al\.?\b", re.IGNORECASE),       "Academic citation form ('et al.')."),
    ("BANNED_YEAR",          re.compile(r"\b(19|20)\d{2}\b"),                    "Year stamp (e.g. '2012'). Citations belong in chord library only."),
    ("BANNED_WINNER_FRAMING",re.compile(r"\b(wins?|loses?|winner|loser|better than|worse than|beats?)\b", re.IGNORECASE),
                                                                                  "Winner/loser framing — Brain Diff is strategy comparison, not contest."),
)


@dataclass
class BannedHit:
    code: str
    detail: str
    matched_text: str


def find_banned_patterns(text: str) -> list[BannedHit]:
    """Return all banned-pattern hits in the text. Empty list = clean."""
    hits: list[BannedHit] = []
    for code, pattern, detail in _BANNED_RULES:
        for m in pattern.finditer(text):
            hits.append(BannedHit(code=code, detail=detail, matched_text=m.group(0)))
    return hits
