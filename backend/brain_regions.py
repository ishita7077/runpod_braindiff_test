import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("braindiff.brain_regions")

REQUIRED_AREAS = {
    "personal_resonance": {"left": ["10r", "10v", "9m", "10d", "32", "25"], "right": ["10r", "10v", "9m", "10d", "32", "25"]},
    "social_thinking": {"right": ["PGi", "PGs", "TPOJ1", "TPOJ2", "TPOJ3"]},
    "brain_effort": {"left": ["46", "p9-46v", "a9-46v", "8C", "8Av"]},
    "language_depth": {"left": ["44", "45", "PSL", "STV", "STSdp", "STSvp"]},
    "gut_reaction": {"left": ["AVI", "AAIC", "MI"], "right": ["AVI", "AAIC", "MI"]},
}


def _decode_names(names):
    return [n.decode() if isinstance(n, bytes) else str(n) for n in names]


def _candidates(area: str, hemi: str) -> list[str]:
    prefix = "L" if hemi == "left" else "R"
    hemi_short = "lh" if hemi == "left" else "rh"
    hemi_ctx = "ctx_lh" if hemi == "left" else "ctx_rh"
    base = [area, f"{prefix}_{area}_ROI", f"{prefix}_{area}", f"{hemi_short}.{area}", f"{hemi_ctx}_{area}"]
    if area == "32":
        for alias in ["d32", "p32", "s32", "a32pr", "p32pr"]:
            base.extend([alias, f"{prefix}_{alias}_ROI", f"{prefix}_{alias}", f"{hemi_short}.{alias}", f"{hemi_ctx}_{alias}"])
    return base


def load_hcp_annotations(atlas_dir: str = "atlases"):
    import nibabel as nib
    atlas_path = Path(atlas_dir)
    lh_path = atlas_path / "lh.HCP-MMP1.annot"
    rh_path = atlas_path / "rh.HCP-MMP1.annot"
    if not lh_path.exists() or not rh_path.exists():
        raise FileNotFoundError(f"Missing HCP MMP1.0 annotation files at {lh_path} and/or {rh_path}")
    labels_lh, _, names_lh = nib.freesurfer.read_annot(str(lh_path))
    labels_rh, _, names_rh = nib.freesurfer.read_annot(str(rh_path))
    return labels_lh, labels_rh, _decode_names(names_lh), _decode_names(names_rh)


def _downsample_labels_to_fsaverage5(labels: np.ndarray, hemi: str, atlas_dir: str) -> np.ndarray:
    if labels.shape[0] == 10242:
        return labels
    if labels.shape[0] != 163842:
        raise ValueError(f"Unsupported label vertex count for {hemi}: {labels.shape[0]}")
    atlas_path = Path(atlas_dir)
    map_name = "left_fsaverage_to_fsaverage5.npy" if hemi == "left" else "right_fsaverage_to_fsaverage5.npy"
    map_path = atlas_path / map_name
    if not map_path.exists():
        raise FileNotFoundError(f"Missing local fsaverage→fsaverage5 mapping file: {map_path}")
    nearest_idx = np.load(map_path)
    if nearest_idx.shape[0] != 10242:
        raise ValueError(f"Unexpected mapping shape for {map_name}: {nearest_idx.shape}")
    return labels[nearest_idx]


def build_vertex_masks(atlas_dir: str = "atlases"):
    labels_lh, labels_rh, names_lh, names_rh = load_hcp_annotations(atlas_dir)
    labels_lh = _downsample_labels_to_fsaverage5(labels_lh, "left", atlas_dir)
    labels_rh = _downsample_labels_to_fsaverage5(labels_rh, "right", atlas_dir)
    hemi_len = len(labels_lh)
    total_len = hemi_len + len(labels_rh)
    if total_len != 20484:
        raise ValueError(f"Expected 20484 total vertices, got {total_len}")
    masks = {}
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
                        full_mask[offset:offset+hemi_len] |= (labels == idx)
                        matched_areas += 1
                        found = True
                        break
                if not found:
                    raise ValueError(f"Missing atlas area: {dim_name}/{hemi}/{area}")
        vertex_count = int(full_mask.sum())
        if vertex_count == 0:
            raise ValueError(f"ROI mask has zero vertices: {dim_name}")
        masks[dim_name] = {"mask": full_mask, "vertex_count": vertex_count, "matched_areas": matched_areas}
    return masks
