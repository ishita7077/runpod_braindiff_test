from backend.differ import compute_diff


def test_diff_symmetry_property() -> None:
    scores_a = {
        "personal_resonance": {"normalized_signed_mean": 0.2},
        "social_thinking": {"normalized_signed_mean": -0.1},
    }
    scores_b = {
        "personal_resonance": {"normalized_signed_mean": -0.3},
        "social_thinking": {"normalized_signed_mean": 0.4},
    }
    ab = compute_diff(scores_a, scores_b)
    ba = compute_diff(scores_b, scores_a)
    for dim in scores_a:
        assert round(ab[dim]["delta"] + ba[dim]["delta"], 6) == 0.0

