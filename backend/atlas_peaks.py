"""Optional HCP label at the vertex of largest |Δ| (fsaverage5), for UI hints."""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger("braindiff.atlas_peaks")

_CACHE: tuple[Any, ...] | None = None


def _label_arrays(atlas_dir: str) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    from backend.brain_regions import _downsample_labels_to_fsaverage5, load_hcp_annotations

    labels_lh, labels_rh, names_lh, names_rh = load_hcp_annotations(atlas_dir)
    labels_lh = _downsample_labels_to_fsaverage5(labels_lh, "left", atlas_dir)
    labels_rh = _downsample_labels_to_fsaverage5(labels_rh, "right", atlas_dir)
    _CACHE = (labels_lh, labels_rh, names_lh, names_rh)
    return _CACHE


def describe_peak_abs_delta(vertex_delta: np.ndarray, atlas_dir: str | None = None) -> dict[str, Any] | None:
    """Return HCP MMP1.0 region name at the vertex with maximum absolute contrast."""
    atlas_dir = atlas_dir or os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases")
    if vertex_delta.shape[0] != 20484:
        return None
    try:
        labels_lh, labels_rh, names_lh, names_rh = _label_arrays(atlas_dir)
    except Exception as err:
        logger.warning("atlas_peaks:load_failed: %s", err)
        return None

    absv = np.abs(np.asarray(vertex_delta, dtype=np.float64))
    if float(absv.max()) < 1e-12:
        return None

    i = int(np.argmax(absv))
    if i < 10242:
        hemi = "left"
        vi = i
        lab = int(labels_lh[vi])
        names = names_lh
    else:
        hemi = "right"
        vi = i - 10242
        lab = int(labels_rh[vi])
        names = names_rh

    name = str(names[lab]) if 0 <= lab < len(names) else "unknown"
    return {
        "hemisphere": hemi,
        "vertex_index_hemi": vi,
        "vertex_index_flat": i,
        "label_index": lab,
        "label": name,
        "abs_delta": float(absv[i]),
    }
