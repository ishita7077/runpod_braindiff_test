from typing import Any
import numpy as np

def _bootstrap_ci(samples: np.ndarray, n_boot: int = 200) -> tuple[float, float, float]:
    if samples.size == 0:
        return 0.0, 0.0, 0.0
    if samples.size == 1:
        val = float(samples[0])
        return val, val, 1.0 if val != 0 else 0.0
    rng = np.random.default_rng(42)
    means = np.empty(n_boot, dtype=np.float32)
    for i in range(n_boot):
        means[i] = float(rng.choice(samples, size=samples.size, replace=True).mean())
    ci_low, ci_high = np.percentile(means, [2.5, 97.5])
    sign_consistency = float(max((means > 0).mean(), (means < 0).mean()))
    return float(ci_low), float(ci_high), sign_consistency

def compute_diff(scores_a: dict[str, dict[str, Any]], scores_b: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    diff = {}
    for dim_name in scores_a:
        a = float(scores_a[dim_name].get('normalized_signed_mean', 0.0))
        b = float(scores_b[dim_name].get('normalized_signed_mean', 0.0))
        delta = b - a
        magnitude = abs(delta)
        pv_a = scores_a[dim_name].get('per_vertex_mean')
        pv_b = scores_b[dim_name].get('per_vertex_mean')
        if pv_a is not None and pv_b is not None:
            ci_low, ci_high, sign_consistency = _bootstrap_ci(np.asarray(pv_b) - np.asarray(pv_a))
        else:
            ci_low, ci_high, sign_consistency = delta, delta, (1.0 if delta != 0 else 0.0)
        if magnitude < 0.005:
            direction = 'neutral'
            confidence = 'too_close_to_call'
        elif magnitude < 0.02:
            direction = 'B_higher' if delta > 0 else 'A_higher'
            confidence = 'directional_signal'
        else:
            direction = 'B_higher' if delta > 0 else 'A_higher'
            confidence = 'clear_signal'
        diff[dim_name] = {
            'score_a': round(a, 6), 'score_b': round(b, 6), 'delta': round(delta, 6),
            'direction': direction, 'magnitude': round(magnitude, 6), 'confidence': confidence,
            'timeseries_a': list(scores_a[dim_name].get('timeseries', [])),
            'timeseries_b': list(scores_b[dim_name].get('timeseries', [])),
            'ci_low': round(ci_low, 6), 'ci_high': round(ci_high, 6), 'sign_consistency': round(sign_consistency, 4),
        }
    return diff
