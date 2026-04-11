"""Cached fsaverage5 pial mesh coordinates for WebGL brain viewer."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger("braindiff.brain_mesh")

_CACHE: dict[str, Any] | None = None


def _mesh_arrays(mesh: Any) -> tuple[np.ndarray, np.ndarray]:
    coords = getattr(mesh, "coordinates", None)
    faces = getattr(mesh, "faces", None)
    if coords is None:
        coords = getattr(mesh, "coordinates_", None)
    if faces is None:
        faces = getattr(mesh, "faces_", None)
    if coords is None or faces is None:
        raise AttributeError("Surface mesh missing coordinates/faces")
    return np.asarray(coords, dtype=np.float64), np.asarray(faces, dtype=np.int32)


def build_brain_mesh_payload(*, cache_dir: str | None = None) -> dict[str, Any]:
    """Return left/right pial mesh for fsaverage5 (10242 verts each hemisphere)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    base = Path(cache_dir or os.getenv("BRAIN_DIFF_CACHE_DIR", "cache"))
    base.mkdir(parents=True, exist_ok=True)
    cache_path = base / "brain_mesh.json"

    if cache_path.exists():
        try:
            _CACHE = json.loads(cache_path.read_text(encoding="utf-8"))
            logger.info("brain_mesh:loaded cache path=%s", cache_path)
            return _CACHE
        except Exception as err:
            logger.warning("brain_mesh:cache_read_failed: %s", err)

    from nilearn import datasets
    from nilearn.surface import load_surf_mesh

    data_dir = str(Path("atlases/nilearn_data").resolve()) if Path("atlases/nilearn_data").exists() else None
    fsavg = datasets.fetch_surf_fsaverage(mesh="fsaverage5", data_dir=data_dir)
    # fetch_surf_fsaverage returns file paths (str), not mesh objects — load via nilearn.surface.
    lh_c, lh_f = _mesh_arrays(load_surf_mesh(fsavg.pial_left))
    rh_c, rh_f = _mesh_arrays(load_surf_mesh(fsavg.pial_right))

    _CACHE = {
        "format": "fsaverage5_pial",
        "lh_coord": lh_c.astype(float).tolist(),
        "lh_faces": lh_f.astype(int).tolist(),
        "rh_coord": rh_c.astype(float).tolist(),
        "rh_faces": rh_f.astype(int).tolist(),
    }
    try:
        cache_path.write_text(json.dumps(_CACHE), encoding="utf-8")
        logger.info("brain_mesh:wrote cache path=%s", cache_path)
    except Exception as err:
        logger.warning("brain_mesh:cache_write_failed: %s", err)
    return _CACHE
