from __future__ import annotations

from typing import Any

DIMENSION_FRAMING = {
    "personal_resonance": {
        "noun": "self-relevance",
        "plain": "feels more about me",
        "a_tip": "Make the message more universal, detached, or observational.",
        "b_tip": "Use second-person framing, concrete stakes, or personal consequences.",
    },
    "social_thinking": {
        "noun": "social reasoning",
        "plain": "makes people think more about other people",
        "a_tip": "Lean into relationships, motives, consequences, or group dynamics.",
        "b_tip": "Strip back social context and focus on facts or direct instruction.",
    },
    "brain_effort": {
        "noun": "cognitive effort",
        "plain": "asks the brain to work harder",
        "a_tip": "Shorten sentences, reduce abstraction, and simplify structure.",
        "b_tip": "Add precision, nuance, or more layered reasoning.",
    },
    "language_depth": {
        "noun": "language depth",
        "plain": "engages deeper meaning-making",
        "a_tip": "Use simpler words and flatter syntax to keep things surface-level.",
        "b_tip": "Use richer phrasing, layered meaning, or stronger semantic contrast.",
    },
    "gut_reaction": {
        "noun": "visceral salience",
        "plain": "lands more viscerally",
        "a_tip": "Lower the emotional temperature and remove vivid sensory triggers.",
        "b_tip": "Add vivid detail, immediacy, tension, or felt stakes.",
    },
}

INTENSITY_LABELS = [
    (0.0, "Minimal"),
    (0.015, "Subtle"),
    (0.05, "Moderate"),
    (0.12, "Strong"),
    (0.22, "Very strong"),
]


def _strength_label(magnitude: float) -> str:
    label = "Minimal"
    for threshold, candidate in INTENSITY_LABELS:
        if magnitude >= threshold:
            label = candidate
    return label


def _winner_label(direction: str) -> str:
    if direction == "A_higher":
        return "Version A"
    if direction == "B_higher":
        return "Version B"
    return "Neither version"


def _top_sides(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    top_a = next((r for r in rows if r["direction"] == "A_higher" and not r.get("low_confidence")), None)
    top_b = next((r for r in rows if r["direction"] == "B_higher" and not r.get("low_confidence")), None)
    return top_a, top_b


def build_insight_payload(rows: list[dict[str, Any]], warnings: list[str] | None = None) -> dict[str, Any]:
    warnings = warnings or []
    ordered = sorted(rows, key=lambda row: float(row["magnitude"]), reverse=True)
    strongest = ordered[0] if ordered else None
    top_a, top_b = _top_sides(ordered)
    stable_rows = [r for r in ordered if not r.get("low_confidence") and r["direction"] != "neutral"]
    similar_rows = [r for r in ordered if r.get("low_confidence") or r["direction"] == "neutral"]

    if strongest is None:
        return {
            "headline": "No meaningful difference detected",
            "subhead": "The two versions look effectively similar on this run.",
            "hero_metrics": [],
            "what_changed": [],
            "what_stayed_similar": [],
            "actionables": [],
            "cool_factor": "TRIBEv2 is comparing predicted average-brain cortical response, not just surface text features.",
            "scientific_note": "These are directional cortical contrasts, not engagement or virality predictions.",
        }

    frame = DIMENSION_FRAMING[strongest["key"]]
    winning_version = _winner_label(strongest["direction"])
    strength = _strength_label(float(strongest["magnitude"]))

    if strongest["direction"] == "neutral" or strongest.get("low_confidence"):
        headline = "The versions are close, with only weak directional differences"
        subhead = "This looks more like a nuance tradeoff than a clear winner."
    else:
        headline = f"{winning_version} shifts the brain response most on {strongest['label'].lower()}"
        subhead = f"The clearest tradeoff is a {strength.lower()} contrast in how the message {frame['plain']}."

    hero_metrics: list[dict[str, str]] = []
    if strongest:
        hero_metrics.append(
            {
                "label": "Biggest shift",
                "value": strongest["label"],
                "detail": f"{winning_version} · {strength}",
            }
        )
    if top_a and top_b:
        hero_metrics.append(
            {
                "label": "Core tradeoff",
                "value": f"{top_a['label']} vs {top_b['label']}",
                "detail": "A and B are pulling in meaningfully different directions",
            }
        )
    if similar_rows:
        hero_metrics.append(
            {
                "label": "Stable dimension",
                "value": similar_rows[0]["label"],
                "detail": "Both versions process this in roughly the same way",
            }
        )

    what_changed = []
    for row in stable_rows[:3]:
        framing = DIMENSION_FRAMING[row["key"]]
        what_changed.append(
            {
                "title": f"{_winner_label(row['direction'])} on {row['label']}",
                "body": f"{_winner_label(row['direction'])} shows a {_strength_label(float(row['magnitude'])).lower()} contrast here, which usually means the content {framing['plain']}",
            }
        )

    what_stayed_similar = []
    for row in similar_rows[:2]:
        framing = DIMENSION_FRAMING[row["key"]]
        what_stayed_similar.append(
            {
                "title": row["label"],
                "body": f"Both versions are processing this dimension similarly, so the real decision probably lives elsewhere than {framing['noun']}.",
            }
        )

    actionables = []
    if top_b:
        framing = DIMENSION_FRAMING[top_b["key"]]
        actionables.append(
            {
                "title": f"If you want more of Version B's effect",
                "body": framing["b_tip"],
            }
        )
    if top_a:
        framing = DIMENSION_FRAMING[top_a["key"]]
        actionables.append(
            {
                "title": f"If you want more of Version A's effect",
                "body": framing["a_tip"],
            }
        )
    if top_a and top_b:
        actionables.append(
            {
                "title": "Best hybrid move",
                "body": f"Keep {top_b['label'].lower()} from B, but preserve {top_a['label'].lower()} from A. That gives you the strongest combined tradeoff in this run.",
            }
        )

    cool_factor = (
        "This comparison comes from predicted cortical contrasts across two versions of your content — "
        "the interesting part is not the score itself, but where the average-brain response is diverging."
    )
    scientific_note = (
        "Read this as a directional neuroscience-informed compare, not a literal behavioral forecast. "
        "TRIBEv2 predicts average cortical response patterns; it does not predict clicks, likes, or individual minds."
    )
    if warnings:
        scientific_note += " Warnings: " + " | ".join(warnings)

    return {
        "headline": headline,
        "subhead": subhead,
        "hero_metrics": hero_metrics,
        "what_changed": what_changed,
        "what_stayed_similar": what_stayed_similar,
        "actionables": actionables,
        "cool_factor": cool_factor,
        "scientific_note": scientific_note,
    }
