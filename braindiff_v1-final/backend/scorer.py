import logging
from typing import Any

import numpy as np

logger = logging.getLogger("braindiff.scorer")


def score_predictions(preds: np.ndarray, masks: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], float]:
    if preds.ndim != 2:
        raise ValueError(f"Expected 2D predictions, got shape {preds.shape}")
    if preds.shape[1] != 20484:
        raise ValueError(f"Expected 20484 vertices, got {preds.shape[1]}")

    whole_brain_median = float(np.median(np.abs(preds)))
    if whole_brain_median < 1e-10:
        logger.warning("whole brain median too small; applying epsilon")
        whole_brain_median = 1e-10

    scores: dict[str, dict[str, Any]] = {}
    for dim_name, dim_data in masks.items():
        mask = dim_data["mask"]
        if mask.shape[0] != preds.shape[1]:
            raise ValueError(f"Mask length mismatch for {dim_name}: {mask.shape[0]}")
        if int(mask.sum()) == 0:
            raise ValueError(f"Mask has zero vertices for {dim_name}")

        regional_signed = preds[:, mask]
        raw_signed_mean = float(regional_signed.mean())
        normalized_signed_mean = raw_signed_mean / whole_brain_median
        raw_abs_mean = float(np.abs(regional_signed).mean())
        timeseries = regional_signed.mean(axis=1).tolist()

        scores[dim_name] = {
            "raw_signed_mean": raw_signed_mean,
            "normalized_signed_mean": normalized_signed_mean,
            "raw_abs_mean": raw_abs_mean,
            "timeseries": timeseries,
            "vertex_count": int(mask.sum()),
        }

    return scores, whole_brain_median

