from backend.insight_engine import build_insight_payload


def test_insight_payload_builds_useful_sections():
    rows = [
        {
            "key": "social_thinking",
            "label": "Social Thinking",
            "direction": "A_higher",
            "magnitude": 0.18,
            "low_confidence": False,
            "confidence": "high",
        },
        {
            "key": "gut_reaction",
            "label": "Gut Reaction",
            "direction": "B_higher",
            "magnitude": 0.09,
            "low_confidence": False,
            "confidence": "high",
        },
        {
            "key": "language_depth",
            "label": "Language Depth",
            "direction": "neutral",
            "magnitude": 0.002,
            "low_confidence": True,
            "confidence": "low",
        },
    ]
    payload = build_insight_payload(rows, warnings=["Very short text may produce unreliable results"])
    assert "headline" in payload and payload["headline"]
    assert payload["hero_metrics"]
    assert payload["what_changed"]
    assert payload["what_stayed_similar"]
    assert payload["actionables"]
    assert "Warnings:" in payload["scientific_note"]
