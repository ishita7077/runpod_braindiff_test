from typing import Any


def compute_diff(
    scores_a: dict[str, dict[str, Any]],
    scores_b: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    diff: dict[str, dict[str, Any]] = {}
    for dim_name in scores_a:
        a = float(scores_a[dim_name]["normalized_signed_mean"])
        b = float(scores_b[dim_name]["normalized_signed_mean"])
        delta = b - a
        magnitude = abs(delta)

        if magnitude < 0.005:
            direction = "neutral"
            confidence = "low"
        elif magnitude < 0.02:
            direction = "B_higher" if delta > 0 else "A_higher"
            confidence = "medium"
        else:
            direction = "B_higher" if delta > 0 else "A_higher"
            confidence = "high"

        diff[dim_name] = {
            "score_a": round(a, 6),
            "score_b": round(b, 6),
            "delta": round(delta, 6),
            "direction": direction,
            "magnitude": round(magnitude, 6),
            "confidence": confidence,
        }
    return diff

