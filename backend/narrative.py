from typing import Any

PLAIN_NAMES = {
    "personal_resonance": "personal resonance",
    "social_thinking": "social thinking",
    "brain_effort": "brain effort",
    "language_depth": "language depth",
    "gut_reaction": "gut reaction",
    "memory_encoding": "memory encoding",
    "attention_salience": "attention",
}

DISCOVERY_HEADLINES = {
    "personal_resonance": {
        "B_higher": "Version B activates the brain's self-relevance center more strongly",
        "A_higher": "Version A triggers more self-referential processing",
    },
    "social_thinking": {
        "B_higher": "Version B engages more social reasoning",
        "A_higher": "Version A engages more social reasoning",
    },
    "brain_effort": {
        "B_higher": "Version B demands higher cognitive effort",
        "A_higher": "Version A demands higher cognitive effort",
    },
    "language_depth": {
        "B_higher": "Version B drives deeper meaning extraction",
        "A_higher": "Version A drives deeper meaning extraction",
    },
    "gut_reaction": {
        "B_higher": "Version B produces a stronger visceral neural response",
        "A_higher": "Version A produces a stronger visceral neural response",
    },
    "memory_encoding": {
        "B_higher": "Version B is more likely to be remembered",
        "A_higher": "Version A is more likely to be remembered",
    },
    "attention_salience": {
        "B_higher": "Version B captures stronger neural attention",
        "A_higher": "Version A captures stronger neural attention",
    },
}


def build_headline(diff: dict[str, dict[str, Any]]) -> str:
    top = max(diff.items(), key=lambda item: item[1]["magnitude"])
    dim_name, payload = top
    if payload["confidence"] == "too_close_to_call":
        return "Nearly identical brain response - difference may be noise"
    direction = payload["direction"]
    discovery = DISCOVERY_HEADLINES.get(dim_name, {}).get(direction)
    if discovery:
        return discovery
    dim_plain = PLAIN_NAMES[dim_name]
    if direction == "B_higher":
        return f"Version B hits harder on {dim_plain}"
    return f"Version A hits harder on {dim_plain}"

