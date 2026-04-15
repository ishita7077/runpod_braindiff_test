from __future__ import annotations

import re
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
    "memory_encoding": {
        "noun": "memory encoding likelihood",
        "plain": "is more likely to be remembered",
        "a_tip": "Add concrete personal stakes or vivid details to increase encoding drive.",
        "b_tip": "Reduce vividness and emotional salience if recall is not the goal.",
    },
    "attention_salience": {
        "noun": "attentional engagement",
        "plain": "captures and holds attention",
        "a_tip": "Increase novelty, urgency, and explicit salience cues to pull attention faster.",
        "b_tip": "Reduce urgency cues and lower novelty if sustained attention is not needed.",
    },
}

INTENSITY_LABELS = [
    (0.0, "Minimal"),
    (0.015, "Subtle"),
    (0.05, "Moderate"),
    (0.12, "Strong"),
    (0.22, "Very strong"),
]

DISCOVERY_TEMPLATES = {
    "personal_resonance": {
        "B_higher": "{b_quality} activates the brain's self-relevance center {pct} more than {a_quality}",
        "A_higher": "{a_quality} triggers more self-referential processing than {b_quality}",
    },
    "social_thinking": {
        "B_higher": "{b_quality} makes the brain think about other people {pct} more than {a_quality}",
        "A_higher": "{a_quality} engages more social reasoning than {b_quality}",
    },
    "brain_effort": {
        "B_higher": "{b_quality} makes the brain work {pct} harder",
        "A_higher": "{a_quality} demands more cognitive effort than {b_quality}",
    },
    "language_depth": {
        "B_higher": "{b_quality} engages the meaning-extraction system {pct} more deeply",
        "A_higher": "{a_quality} triggers deeper semantic processing than {b_quality}",
    },
    "gut_reaction": {
        "B_higher": "{b_quality} hits the brain's visceral center {pct} harder than {a_quality}",
        "A_higher": "{a_quality} produces a stronger gut-level neural response",
    },
    "memory_encoding": {
        "B_higher": "{b_quality} is more likely to be remembered — the brain's encoding system activates {pct} more",
        "A_higher": "{a_quality} triggers stronger memory encoding signals than {b_quality}",
    },
    "attention_salience": {
        "B_higher": "{b_quality} captures more neural attention — the brain's spotlight is brighter",
        "A_higher": "{a_quality} engages the attention network more strongly than {b_quality}",
    },
}

BRAIN_EFFORT_NARRATIVE = {
    "high_effort": (
        "Version {winner} demands significantly more cognitive effort. "
        "This could mean one of three things: "
        "(1) the content is genuinely complex - intrinsic load from a dense topic; "
        "(2) the writing itself is hard to parse - extraneous load from jargon or poor structure; "
        "or (3) the reader is actively learning - germane load from building new understanding. "
        "The brain signal alone can't distinguish which type. Context and your audience decide. "
        "(Sweller, 1988; Owen et al., 2005)"
    ),
    "low_effort": (
        "Version {winner} requires less cognitive effort. "
        "Simpler language, shorter sentences, or more familiar concepts reduce the load on working memory. "
        "This is usually good for broad audiences but may feel too simple for expert readers."
    ),
    "neutral": (
        "Both versions demand similar cognitive effort - the brain works about equally hard to process each one."
    ),
}


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


def _detect_content_quality(text: str) -> str:
    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    word_count = len(words)
    has_you = "you" in words or "your" in words or "you're" in words
    has_jargon = any(w in text.lower() for w in ["optimize", "leverage", "synerg", "vertical", "workflow", "enterprise"])
    has_numbers = any(c.isdigit() for c in text)
    has_question = "?" in text
    avg_word_len = sum(len(w) for w in words) / max(1, word_count)

    if has_you and not has_jargon:
        return "Personal, direct language"
    if has_jargon:
        return "Corporate jargon"
    if has_question:
        return "Question-framed language"
    if has_numbers:
        return "Data-driven language"
    if avg_word_len > 6:
        return "Complex, formal language"
    if avg_word_len < 4.5 and word_count < 20:
        return "Short, punchy language"
    return "This version"


def _discovery_headline(
    strongest: dict[str, Any],
    *,
    text_a: str | None = None,
    text_b: str | None = None,
) -> str:
    key = strongest["key"]
    direction = strongest["direction"]
    template = DISCOVERY_TEMPLATES.get(key, {}).get(direction)
    if not template:
        return f"{_winner_label(direction)} shifts the brain response most on {strongest['label'].lower()}"

    a_quality = _detect_content_quality(text_a or "")
    b_quality = _detect_content_quality(text_b or "")
    if a_quality == "This version":
        a_quality = "Version A"
    if b_quality == "This version":
        b_quality = "Version B"

    pct_value = max(5, int(round(float(strongest.get("magnitude", 0.0)) * 100)))
    pct = f"{pct_value}%"
    return template.format(a_quality=a_quality, b_quality=b_quality, pct=pct)


def build_insight_payload(
    rows: list[dict[str, Any]],
    warnings: list[str] | None = None,
    *,
    narrative_tone: str = "sober",
    text_a: str | None = None,
    text_b: str | None = None,
) -> dict[str, Any]:
    warnings = warnings or []
    punchy = narrative_tone.strip().lower() == "punchy"
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
        headline = _discovery_headline(strongest, text_a=text_a, text_b=text_b)
        if punchy:
            subhead = (
                f"{strength} split on how the message {frame['plain']} — "
                f"that's the sharpest contrast in this run."
            )
        else:
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
        body = (
            f"{_winner_label(row['direction'])} shows a {_strength_label(float(row['magnitude'])).lower()} contrast here, "
            f"which usually means the content {framing['plain']}"
        )
        if row["key"] == "brain_effort":
            if row["direction"] == "neutral" or row.get("low_confidence"):
                body = BRAIN_EFFORT_NARRATIVE["neutral"]
            elif row["direction"] == "B_higher":
                body = BRAIN_EFFORT_NARRATIVE["high_effort"].format(winner="B")
            else:
                body = BRAIN_EFFORT_NARRATIVE["high_effort"].format(winner="A")
        elif row["key"] == "memory_encoding":
            body += (
                " Higher vlPFC activity is associated with stronger encoding drive, "
                "but this is the cortical driver only, not hippocampal completion."
            )
        what_changed.append(
            {
                "title": f"{_winner_label(row['direction'])} on {row['label']}",
                "body": body,
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

    if punchy:
        cool_factor = (
            "Two drafts, one cortical scoreboard — the fun part is watching *where* they diverge, not chasing a single number."
        )
    else:
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
