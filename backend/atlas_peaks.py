"""HCP atlas utilities for fsaverage5: peak detection, per-vertex labels, dimension mapping."""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

logger = logging.getLogger("braindiff.atlas_peaks")

_CACHE: tuple[Any, ...] | None = None
_ATLAS_PAYLOAD: dict[str, Any] | None = None


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


def build_vertex_atlas_payload(atlas_dir: str | None = None) -> dict[str, Any]:
    """Per-vertex HCP region labels + dimension reverse map for the frontend hover tooltip."""
    global _ATLAS_PAYLOAD
    if _ATLAS_PAYLOAD is not None:
        return _ATLAS_PAYLOAD

    atlas_dir = atlas_dir or os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases")
    labels_lh, labels_rh, names_lh, names_rh = _label_arrays(atlas_dir)

    vertex_labels: list[str] = []
    for i in range(10242):
        lab = int(labels_lh[i])
        vertex_labels.append(str(names_lh[lab]) if 0 <= lab < len(names_lh) else "???")
    for i in range(10242):
        lab = int(labels_rh[i])
        vertex_labels.append(str(names_rh[lab]) if 0 <= lab < len(names_rh) else "???")

    from backend.brain_regions import REQUIRED_AREAS, _candidates

    # Vertex labels match HCP annot strings (e.g. L_8BL_ROI); map every candidate alias to Brain Diff dimensions.
    dim_map: dict[str, list[str]] = {}
    for dim_name, hemis in REQUIRED_AREAS.items():
        for hemi, areas in hemis.items():
            for area in areas:
                for cand in _candidates(area, hemi):
                    dim_map.setdefault(cand, [])
                    if dim_name not in dim_map[cand]:
                        dim_map[cand].append(dim_name)

    _ATLAS_PAYLOAD = {"labels": vertex_labels, "dimensions": dim_map}
    return _ATLAS_PAYLOAD
