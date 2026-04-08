import os

import pytest

from backend.differ import compute_diff


@pytest.mark.skipif(
    os.getenv("RUN_TRIBEV2_SANITY", "0") != "1",
    reason="Set RUN_TRIBEV2_SANITY=1 to run semantic sanity checks with full model pipeline.",
)
def test_known_direction_pairs_smoke() -> None:
    # Placeholder shape for phase gate: uses canonical directional expectations.
    # Full semantic validation requires model inference over curated pairs.
    scores_a = {
        "personal_resonance": {"normalized_signed_mean": 0.01},
        "social_thinking": {"normalized_signed_mean": 0.01},
        "brain_effort": {"normalized_signed_mean": 0.03},
        "language_depth": {"normalized_signed_mean": 0.02},
        "gut_reaction": {"normalized_signed_mean": -0.01},
    }
    scores_b = {
        "personal_resonance": {"normalized_signed_mean": 0.05},
        "social_thinking": {"normalized_signed_mean": 0.03},
        "brain_effort": {"normalized_signed_mean": 0.01},
        "language_depth": {"normalized_signed_mean": 0.01},
        "gut_reaction": {"normalized_signed_mean": 0.04},
    }
    diff = compute_diff(scores_a, scores_b)
    assert diff["personal_resonance"]["direction"] == "B_higher"
    assert diff["gut_reaction"]["direction"] == "B_higher"

