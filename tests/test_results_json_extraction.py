"""Phase C.1 — JSON extraction.

Covers every realistic Gemma output shape:
  * raw JSON object
  * JSON in markdown code fences
  * JSON with leading/trailing prose
  * JSON with trailing commas
  * JSON with smart quotes
  * malformed input -> raises typed error
"""

from __future__ import annotations

import pytest

from backend.results.lib.json_extract import (
    JSONExtractionError,
    extract_first_json_object,
)


def test_pure_json() -> None:
    obj = extract_first_json_object('{"text": "hi", "n": 3}')
    assert obj == {"text": "hi", "n": 3}


def test_markdown_fence() -> None:
    raw = "Sure! Here:\n```json\n{\n  \"text\": \"hi\"\n}\n```\nThat's it."
    assert extract_first_json_object(raw) == {"text": "hi"}


def test_unlabelled_fence() -> None:
    raw = "```\n{\"k\": 1}\n```"
    assert extract_first_json_object(raw) == {"k": 1}


def test_leading_prose() -> None:
    raw = "Of course. The output is {\"a\": 1, \"b\": [2, 3]} as requested."
    assert extract_first_json_object(raw) == {"a": 1, "b": [2, 3]}


def test_trailing_comma_in_array() -> None:
    raw = '{"items": [1, 2, 3,]}'
    assert extract_first_json_object(raw) == {"items": [1, 2, 3]}


def test_trailing_comma_in_object() -> None:
    raw = '{"a": 1, "b": 2,}'
    assert extract_first_json_object(raw) == {"a": 1, "b": 2}


def test_smart_quotes() -> None:
    raw = '{“text”: “hi there”}'
    assert extract_first_json_object(raw) == {"text": "hi there"}


def test_braces_inside_strings_are_not_counted() -> None:
    """The balanced-brace walker must respect string state."""
    raw = '{"note": "uses { and } inside", "k": 1}'
    assert extract_first_json_object(raw) == {"note": "uses { and } inside", "k": 1}


def test_escaped_quotes_inside_strings() -> None:
    raw = '{"q": "she said \\"hi\\""}'
    assert extract_first_json_object(raw) == {"q": 'she said "hi"'}


def test_picks_first_object_when_multiple_present() -> None:
    raw = '{"first": 1} and {"second": 2}'
    assert extract_first_json_object(raw) == {"first": 1}


def test_empty_input_raises() -> None:
    with pytest.raises(JSONExtractionError):
        extract_first_json_object("")
    with pytest.raises(JSONExtractionError):
        extract_first_json_object("   \n  ")


def test_no_object_raises() -> None:
    with pytest.raises(JSONExtractionError):
        extract_first_json_object("hello world, no json here")


def test_array_top_level_is_rejected() -> None:
    """Slots must return objects, not arrays. Bare arrays fail the contract."""
    with pytest.raises(JSONExtractionError):
        extract_first_json_object("[1, 2, 3]")


def test_truncated_object_raises() -> None:
    with pytest.raises(JSONExtractionError):
        extract_first_json_object('{"text": "unterminated...')


def test_realistic_gemma_chatter() -> None:
    raw = (
        "Of course. Here is the JSON output you requested.\n\n"
        "```json\n"
        "{\n"
        '  "thesis": "B reaches the gut faster.",\n'
        '  "tradeoff": "A explains; B activates.",\n'
        '  "evidence_refs": ["video_a:0:08", "video_b:0:14"],\n'
        '  "confidence": "medium",\n'  # trailing comma
        "}\n"
        "```\n"
        "Let me know if you'd like adjustments."
    )
    obj = extract_first_json_object(raw)
    assert obj["thesis"] == "B reaches the gut faster."
    assert obj["evidence_refs"] == ["video_a:0:08", "video_b:0:14"]
    assert obj["confidence"] == "medium"
