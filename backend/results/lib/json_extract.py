"""Robust JSON extraction from LLM output — Phase C.1 of the production fix plan.

The Gemma 3 1B model is reliable at producing JSON when asked, but it almost
always wraps the object in chatter:
    Sure, here is the JSON you asked for:
    ```json
    {"text": "..."}
    ```
    Hope that helps!

This module finds the first balanced `{...}` JSON object in any string and
returns it as a dict. It tolerates the common failure modes:
  * leading/trailing prose
  * markdown code fences (``` or ```json)
  * trailing commas inside arrays/objects (Gemma adds these occasionally)
  * smart quotes (the model sometimes emits “…”)

What it does NOT do:
  * "fix" structural errors. If the JSON is broken, we raise a typed error
    so the slot runner can either retry with a repair prompt (Phase C.5) or
    fall through. Silent JSON repair is what "fallback rate hides bugs"
    looks like.

Usage:
    from backend.results.lib.json_extract import (
        extract_first_json_object, JSONExtractionError,
    )
    obj = extract_first_json_object(model_text)  # -> dict
"""

from __future__ import annotations

import json
import re
from typing import Any


class JSONExtractionError(ValueError):
    """Raised when no parseable JSON object can be located in the input."""


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_SMART_QUOTES = {
    "“": '"',  # left double
    "”": '"',  # right double
    "‘": "'",  # left single
    "’": "'",  # right single
}


def _normalise_smart_quotes(text: str) -> str:
    for src, dst in _SMART_QUOTES.items():
        text = text.replace(src, dst)
    return text


def _strip_trailing_commas(text: str) -> str:
    """Remove `,` immediately before `]` or `}` (with whitespace allowed)."""
    return re.sub(r",(\s*[\]}])", r"\1", text)


def _find_balanced_object(text: str) -> str | None:
    """Return the substring of the FIRST balanced `{...}` block, or None.

    Walks the string char-by-char tracking string state (so `{` inside a
    quoted JSON string doesn't count toward depth). Handles backslash-escaped
    quotes inside strings.
    """
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start:i + 1]
    return None


def extract_first_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a noisy LLM response.

    Raises JSONExtractionError on:
      * empty input
      * no `{...}` block found
      * JSON found but not parseable even after smart-quote / trailing-comma fixups
    """
    if not text or not text.strip():
        raise JSONExtractionError("empty input")

    # Try every code-fence block first; otherwise fall back to scanning the
    # whole string. Code-fenced JSON is the most reliable signal when present.
    candidates: list[str] = []
    for match in _FENCE_RE.findall(text):
        balanced = _find_balanced_object(match)
        if balanced:
            candidates.append(balanced)

    full = _find_balanced_object(text)
    if full and full not in candidates:
        candidates.append(full)

    if not candidates:
        raise JSONExtractionError("no balanced {...} object in input")

    last_err: Exception | None = None
    for candidate in candidates:
        for fixup in (lambda s: s,
                      _normalise_smart_quotes,
                      _strip_trailing_commas,
                      lambda s: _strip_trailing_commas(_normalise_smart_quotes(s))):
            try:
                obj = json.loads(fixup(candidate))
            except json.JSONDecodeError as exc:
                last_err = exc
                continue
            if not isinstance(obj, dict):
                last_err = JSONExtractionError(
                    f"top-level JSON value is {type(obj).__name__}, expected object"
                )
                continue
            return obj

    raise JSONExtractionError(f"could not parse JSON from candidates: {last_err}")
