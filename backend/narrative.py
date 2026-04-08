from typing import Any

PLAIN_NAMES = {
    "personal_resonance": "personal resonance",
    "social_thinking": "social thinking",
    "brain_effort": "brain effort",
    "language_depth": "language depth",
    "gut_reaction": "gut reaction",
}


def build_headline(diff: dict[str, dict[str, Any]]) -> str:
    top = max(diff.items(), key=lambda item: item[1]["magnitude"])
    dim_name, payload = top
    if payload["confidence"] == "low":
        return "Nearly identical brain response - difference may be noise"
    dim_plain = PLAIN_NAMES[dim_name]
    if payload["direction"] == "B_higher":
        return f"Version B hits harder on {dim_plain}"
    return f"Version A hits harder on {dim_plain}"

