import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger("braindiff.brain_regions")

DIMENSIONS_HCP = {
    "personal_resonance": {
        "description": "Personal resonance",
        "brain_region": "Medial prefrontal cortex (mPFC)",
        "areas": {"left": ["10r", "10v", "9m", "10d", "32", "25"], "right": ["10r", "10v", "9m", "10d", "32", "25"]},
    },
    "social_thinking": {
        "description": "Social thinking",
        "brain_region": "Temporoparietal junction (TPJ)",
        "areas": {"right": ["PGi", "PGs", "TPOJ1", "TPOJ2", "TPOJ3"]},
    },
    "brain_effort": {
        "description": "Brain effort",
        "brain_region": "Dorsolateral prefrontal cortex (dlPFC)",
        "areas": {"left": ["46", "p9-46v", "a9-46v", "8C", "8Av"]},
    },
    "language_depth": {
        "description": "Language depth",
        "brain_region": "Left language network",
        "areas": {"left": ["44", "45", "PSL", "STV", "STSdp", "STSvp"]},
    },
    "gut_reaction": {
        "description": "Gut reaction",
        "brain_region": "Anterior insula",
        "areas": {"left": ["AVI", "AAIC", "MI"], "right": ["AVI", "AAIC", "MI"]},
    },
    "memory_encoding": {
        "description": "Memory encoding likelihood — how likely the brain is to commit this to long-term storage",
        "brain_region": "Left ventrolateral prefrontal cortex (vlPFC)",
        "areas": {"left": ["44", "45", "47s", "IFSa", "IFSp", "p47r"]},
        "source": "Paller & Wagner 2002; Buckner et al. 1999; Wagner et al. 1998; Neuro-Insight SST validation",
    },
    "attention_salience": {
        "description": "Attentional engagement — how strongly the brain's attention-allocation system is engaged",
        "brain_region": "Dorsal attention network (intraparietal sulcus + frontal eye fields)",
        "areas": {
            "left": ["LIPv", "LIPd", "AIP", "VIP", "MIP", "FEF", "PEF"],
            "right": ["LIPv", "LIPd", "AIP", "VIP", "MIP", "FEF", "PEF"],
        },
        "source": "Corbetta & Shulman 2002; Kastner & Ungerleider 2000",
    },
}

REQUIRED_AREAS = {key: cfg["areas"] for key, cfg in DIMENSIONS_HCP.items()}

DESTRIEUX_FALLBACK = {
    "memory_encoding": {
        "parcels": [
            ("left", "G_front_inf-Opercular"),
            ("left", "G_front_inf-Triangul"),
            ("left", "G_front_inf-Orbital"),
        ],
    },
    "attention_salience": {
        "parcels": [
            ("left", "S_intrapariet_and_P_trans"),
            ("right", "S_intrapariet_and_P_trans"),
            ("left", "G_front_middle"),
            ("right", "G_front_middle"),
        ],
    },
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


def _find_area_index(area: str, hemi: str, label_names: list[str], *, dim_name: str) -> int:
    attempts = _candidates(area, hemi)
    for candidate in attempts:
        if candidate in label_names:
            logger.info(
                "brain_regions:matched area dim=%s hemi=%s area=%s candidate=%s",
                dim_name,
                hemi,
                area,
                candidate,
            )
            return label_names.index(candidate)
    logger.error(
        "brain_regions:missing area dim=%s hemi=%s area=%s attempts=%s",
        dim_name,
        hemi,
        area,
        attempts,
    )
    raise ValueError(f"Missing atlas area: {dim_name}/{hemi}/{area}")


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

    logger.info(
        "NOTE: memory_encoding shares areas 44, 45 with language_depth. Correlation expected and scientifically valid."
    )

    for area in ["47s", "IFSa", "IFSp", "p47r"]:
        # Validate these exist before mask assembly, with full candidate logging.
        _find_area_index(area, "left", names_lh, dim_name="memory_encoding")

    for dim_name, cfg in DIMENSIONS_HCP.items():
        hemis = cfg["areas"]
        full_mask = np.zeros(total_len, dtype=bool)
        matched_areas = 0
        for hemi, areas in hemis.items():
            label_names = names_lh if hemi == "left" else names_rh
            labels = labels_lh if hemi == "left" else labels_rh
            offset = 0 if hemi == "left" else hemi_len
            for area in areas:
                idx = _find_area_index(area, hemi, label_names, dim_name=dim_name)
                full_mask[offset:offset + hemi_len] |= labels == idx
                matched_areas += 1
        vertex_count = int(full_mask.sum())
        if vertex_count == 0:
            raise ValueError(f"ROI mask has zero vertices: {dim_name}")
        masks[dim_name] = {"mask": full_mask, "vertex_count": vertex_count, "matched_areas": matched_areas}
    return masks
