from typing import Any

UI_LABELS = {
    "personal_resonance": "Personal Resonance",
    "social_thinking": "Social Thinking",
    "brain_effort": "Brain Effort",
    "language_depth": "Language Depth",
    "gut_reaction": "Gut Reaction",
}

TOOLTIPS = {
    "personal_resonance": "How much the brain processes this as self-relevant (mPFC)",
    "social_thinking": "How much the brain considers others' perspectives (TPJ)",
    "brain_effort": "How hard the brain works to process this (dlPFC)",
    "language_depth": "How deeply the brain extracts meaning (Broca's + Wernicke's)",
    "gut_reaction": "How viscerally the brain responds (anterior insula)",
}

USER_MEANING = {
    "personal_resonance": "feels more personally relevant",
    "social_thinking": "pulls more social reasoning",
    "brain_effort": "demands more thinking effort",
    "language_depth": "engages deeper meaning-making",
    "gut_reaction": "lands more viscerally",
}


def _strength_label(magnitude: float) -> str:
    if magnitude < 0.005:
        return "Very small"
    if magnitude < 0.02:
        return "Subtle"
    if magnitude < 0.06:
        return "Moderate"
    if magnitude < 0.14:
        return "Strong"
    return "Very strong"


def enrich_dimension_payload(diff: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    max_mag = max((float(v["magnitude"]) for v in diff.values()), default=0.0)
    max_mag = max(max_mag, 1e-9)
    for key, payload in diff.items():
        magnitude = float(payload["magnitude"])
        direction = payload["direction"]
        winner = "Version B" if direction == "B_higher" else "Version A" if direction == "A_higher" else "Neither version"
        confidence = payload["confidence"]
        rows.append(
            {
                "key": key,
                "label": UI_LABELS[key],
                "tooltip": TOOLTIPS[key],
                "meaning": USER_MEANING[key],
                "score_a": payload["score_a"],
                "score_b": payload["score_b"],
                "delta": payload["delta"],
                "direction": direction,
                "magnitude": magnitude,
                "confidence": confidence,
                "low_confidence": confidence == "low",
                "delta_display": f"{payload['delta']:+.3f}",
                "bar_fraction": round(magnitude / max_mag, 6),
                "winner": winner,
                "strength": _strength_label(magnitude),
            }
        )
    rows.sort(key=lambda row: row["magnitude"], reverse=True)
    return rows


def winner_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    b_wins = 0
    a_wins = 0
    tied = 0
    for row in rows:
        if row["low_confidence"] or row["direction"] == "neutral":
            tied += 1
        elif row["direction"] == "B_higher":
            b_wins += 1
        else:
            a_wins += 1
    return {"b_wins": b_wins, "a_wins": a_wins, "tied": tied}
