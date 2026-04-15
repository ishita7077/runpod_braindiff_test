import numpy as np

from backend.differ import compute_diff
from backend.scorer import score_predictions


def test_scoring_uses_normalized_signed_mean():
    preds = np.zeros((2, 20484), dtype=np.float32)
    preds[:, :100] = 2.0
    preds[:, 100:200] = -1.0

    masks = {
        "personal_resonance": {"mask": np.array([True] * 100 + [False] * (20484 - 100), dtype=bool)},
        "social_thinking": {"mask": np.array([False] * 100 + [True] * 100 + [False] * (20484 - 200), dtype=bool)},
    }
    scores, ref = score_predictions(preds, masks)
    assert ref > 0.0
    assert scores["personal_resonance"]["raw_signed_mean"] == 2.0
    assert scores["personal_resonance"]["normalized_signed_mean"] > 0.0
    assert scores["social_thinking"]["raw_signed_mean"] == -1.0
    assert scores["social_thinking"]["normalized_signed_mean"] < 0.0


def test_diff_marks_low_confidence_as_neutral():
    scores_a = {"gut_reaction": {"normalized_signed_mean": 0.0100}}
    scores_b = {"gut_reaction": {"normalized_signed_mean": 0.0139}}
    diff = compute_diff(scores_a, scores_b)
    assert diff["gut_reaction"]["magnitude"] < 0.005
    assert diff["gut_reaction"]["direction"] == "neutral"
    assert diff["gut_reaction"]["confidence"] == "too_close_to_call"

