import logging
from typing import Any
import numpy as np
logger = logging.getLogger("braindiff.scorer")

def reference_scale(preds: np.ndarray) -> float:
    median_abs = float(np.median(np.abs(preds)))
    if median_abs > 1e-6:
        return median_abs
    mean_abs = float(np.mean(np.abs(preds)))
    if mean_abs > 1e-6:
        logger.warning("whole-brain median near zero; falling back to mean absolute activation")
        return mean_abs
    return 1e-6

def score_predictions(preds: np.ndarray, masks: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], float]:
    if preds.ndim != 2 or preds.shape[1] != 20484:
        raise ValueError(f"Expected predictions shape (*, 20484), got {preds.shape}")
    whole_brain_median = reference_scale(preds)
    scores = {}
    for dim_name, dim_data in masks.items():
        mask = dim_data['mask']
        regional_signed = preds[:, mask]
        raw_signed_mean = float(regional_signed.mean())
        normalized_signed_mean = raw_signed_mean / whole_brain_median
        raw_abs_mean = float(np.abs(regional_signed).mean())
        timeseries = (regional_signed.mean(axis=1) / whole_brain_median).tolist()
        per_vertex_mean = regional_signed.mean(axis=0) / whole_brain_median
        scores[dim_name] = {
            'raw_signed_mean': raw_signed_mean,
            'normalized_signed_mean': normalized_signed_mean,
            'raw_abs_mean': raw_abs_mean,
            'timeseries': timeseries,
            'vertex_count': int(mask.sum()),
            'per_vertex_mean': per_vertex_mean,
        }
    return scores, whole_brain_median
