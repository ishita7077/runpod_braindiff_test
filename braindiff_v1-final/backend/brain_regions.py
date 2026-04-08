import logging
import os
from pathlib import Path

import nibabel as nib
import numpy as np
from nilearn import datasets
from nilearn.surface import load_surf_mesh
from scipy.spatial import cKDTree

logger = logging.getLogger("braindiff.brain_regions")

REQUIRED_AREAS = {
    "personal_resonance": {
        "left": ["10r", "10v", "9m", "10d", "32", "25"],
        "right": ["10r", "10v", "9m", "10d", "32", "25"],
    },
    "social_thinking": {
        "right": ["PGi", "PGs", "TPOJ1", "TPOJ2", "TPOJ3"],
    },
    "brain_effort": {
        "left": ["46", "p9-46v", "a9-46v", "8C", "8Av"],
    },
    "language_depth": {
        "left": ["44", "45", "PSL", "STV", "STSdp", "STSvp"],
    },
    "gut_reaction": {
        "left": ["AVI", "AAIC", "MI"],
        "right": ["AVI", "AAIC", "MI"],
    },
}


def _decode_names(names: list[bytes | str]) -> list[str]:
    return [n.decode() if isinstance(n, bytes) else str(n) for n in names]


def _candidates(area: str, hemi: str) -> list[str]:
    prefix = "L" if hemi == "left" else "R"
    hemi_short = "lh" if hemi == "left" else "rh"
    hemi_ctx = "ctx_lh" if hemi == "left" else "ctx_rh"
    base = [
        area,
        f"{prefix}_{area}_ROI",
        f"{prefix}_{area}",
        f"{hemi_short}.{area}",
        f"{hemi_ctx}_{area}",
    ]
    if area == "32":
        for alias in ["d32", "p32", "s32", "a32pr", "p32pr"]:
            base.extend(
                [
                    alias,
                    f"{prefix}_{alias}_ROI",
                    f"{prefix}_{alias}",
                    f"{hemi_short}.{alias}",
                    f"{hemi_ctx}_{alias}",
                ]
            )
    return base


def load_hcp_annotations(atlas_dir: str = "atlases") -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    atlas_path = Path(atlas_dir)
    lh_path = atlas_path / "lh.HCP-MMP1.annot"
    rh_path = atlas_path / "rh.HCP-MMP1.annot"
    if not lh_path.exists() or not rh_path.exists():
        raise FileNotFoundError(
            f"Missing HCP MMP1.0 annotation files at {lh_path} and/or {rh_path}"
        )

    labels_lh, _, names_lh = nib.freesurfer.read_annot(str(lh_path))
    labels_rh, _, names_rh = nib.freesurfer.read_annot(str(rh_path))
    clean_lh = _decode_names(names_lh)
    clean_rh = _decode_names(names_rh)
    logger.info(
        "load_hcp_annotations:ok left_labels=%s right_labels=%s",
        len(clean_lh),
        len(clean_rh),
    )
    return labels_lh, labels_rh, clean_lh, clean_rh


def _approximate_downsample(labels: np.ndarray, hemi: str) -> np.ndarray:
    strict = os.getenv("BRAIN_DIFF_STRICT_ATLAS", "0") == "1"
    if strict:
        raise RuntimeError(
            f"Strict atlas mode enabled; accurate fsaverage→fsaverage5 mapping required for {hemi}"
        )
    os.environ["BRAIN_DIFF_ATLAS_APPROX_USED"] = "1"
    idx = np.linspace(0, labels.shape[0] - 1, 10242).round().astype(int)
    logger.warning(
        "approximate atlas downsample in use for hemi=%s src_vertices=%s dst_vertices=%s",
        hemi,
        labels.shape[0],
        len(idx),
    )
    return labels[idx]


def _downsample_labels_to_fsaverage5(labels: np.ndarray, hemi: str) -> np.ndarray:
    # Atlas labels from figshare are on fsaverage (163842 vertices/hemi).
    # TRIBEv2 predictions are on fsaverage5 (10242 vertices/hemi).
    if labels.shape[0] == 10242:
        return labels
    if labels.shape[0] != 163842:
        raise ValueError(f"Unsupported label vertex count for {hemi}: {labels.shape[0]}")

    mapping_path = Path(os.getenv("BRAIN_DIFF_ATLAS_MAP_DIR", "atlases")) / f"{hemi}_fsaverage_to_fsaverage5.npy"
    if mapping_path.exists():
        idx = np.load(mapping_path)
        logger.info("using cached atlas downsample map hemi=%s path=%s", hemi, mapping_path)
        return labels[idx]

    try:
        fsavg = datasets.fetch_surf_fsaverage(mesh="fsaverage")
        fsavg5 = datasets.fetch_surf_fsaverage(mesh="fsaverage5")
        pial_src = fsavg.pial_left if hemi == "left" else fsavg.pial_right
        pial_dst = fsavg5.pial_left if hemi == "left" else fsavg5.pial_right
        src_coords, _ = load_surf_mesh(pial_src)
        dst_coords, _ = load_surf_mesh(pial_dst)

        tree = cKDTree(src_coords)
        _, nearest_idx = tree.query(dst_coords, k=1)
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        np.save(mapping_path, nearest_idx.astype(np.int32))
        downsampled = labels[nearest_idx]
        logger.info(
            "downsample_labels:hemi=%s src_vertices=%s dst_vertices=%s",
            hemi,
            labels.shape[0],
            downsampled.shape[0],
        )
        return downsampled
    except Exception as err:
        logger.warning("accurate atlas downsample unavailable for hemi=%s: %s", hemi, err)
        return _approximate_downsample(labels, hemi)


def build_vertex_masks(atlas_dir: str = "atlases") -> dict[str, dict[str, np.ndarray | int]]:
    os.environ.pop("BRAIN_DIFF_ATLAS_APPROX_USED", None)
    labels_lh, labels_rh, names_lh, names_rh = load_hcp_annotations(atlas_dir=atlas_dir)
    labels_lh = _downsample_labels_to_fsaverage5(labels_lh, "left")
    labels_rh = _downsample_labels_to_fsaverage5(labels_rh, "right")
    hemi_len = len(labels_lh)
    if len(labels_lh) != len(labels_rh):
        raise ValueError(
            f"Hemisphere vertex length mismatch: lh={len(labels_lh)} rh={len(labels_rh)}"
        )

    total_len = len(labels_lh) + len(labels_rh)
    if total_len != 20484:
        raise ValueError(f"Expected 20484 total vertices, got {total_len}")

    masks: dict[str, dict[str, np.ndarray | int]] = {}
    for dim_name, hemis in REQUIRED_AREAS.items():
        full_mask = np.zeros(total_len, dtype=bool)
        matched_areas = 0
        for hemi, areas in hemis.items():
            label_names = names_lh if hemi == "left" else names_rh
            labels = labels_lh if hemi == "left" else labels_rh
            offset = 0 if hemi == "left" else hemi_len

            for area in areas:
                found = False
                for candidate in _candidates(area, hemi):
                    if candidate in label_names:
                        idx = label_names.index(candidate)
                        hemi_mask = labels == idx
                        full_mask[offset : offset + hemi_len] |= hemi_mask
                        matched_areas += 1
                        found = True
                        break
                if not found:
                    logger.error(
                        "build_vertex_masks:missing dim=%s hemi=%s area=%s", dim_name, hemi, area
                    )
                    raise ValueError(f"Missing atlas area: {dim_name}/{hemi}/{area}")

        vertex_count = int(full_mask.sum())
        if vertex_count == 0:
            raise ValueError(f"ROI mask has zero vertices: {dim_name}")
        masks[dim_name] = {"mask": full_mask, "vertex_count": vertex_count, "matched_areas": matched_areas}

    logger.info(
        "build_vertex_masks:ok %s approx=%s",
        {
            k: {"vertex_count": v["vertex_count"], "matched_areas": v["matched_areas"]}
            for k, v in masks.items()
        },
        os.getenv("BRAIN_DIFF_ATLAS_APPROX_USED") == "1",
    )
    return masks
