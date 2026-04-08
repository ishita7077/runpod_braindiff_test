import logging
from pathlib import Path
from typing import Union

import nibabel as nib

logger = logging.getLogger("braindiff.test_atlas_labels")

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


def _decode(names: list[Union[bytes, str]]) -> list[str]:
    return [n.decode() if isinstance(n, bytes) else str(n) for n in names]


def _candidates(area: str, hemi: str) -> list[str]:
    base = [
        area,
        f"L_{area}_ROI" if hemi == "left" else f"R_{area}_ROI",
        f"L_{area}" if hemi == "left" else f"R_{area}",
        f"lh.{area}" if hemi == "left" else f"rh.{area}",
        f"ctx_lh_{area}" if hemi == "left" else f"ctx_rh_{area}",
    ]
    if area == "32":
        for alias in ["d32", "p32", "s32", "a32pr", "p32pr"]:
            base.extend(
                [
                    alias,
                    f"L_{alias}_ROI" if hemi == "left" else f"R_{alias}_ROI",
                    f"L_{alias}" if hemi == "left" else f"R_{alias}",
                    f"lh.{alias}" if hemi == "left" else f"rh.{alias}",
                    f"ctx_lh_{alias}" if hemi == "left" else f"ctx_rh_{alias}",
                ]
            )
    return base


def test_atlas_loads_and_contains_all_areas() -> None:
    atlas_dir = Path("atlases")
    lh_path = atlas_dir / "lh.HCP-MMP1.annot"
    rh_path = atlas_dir / "rh.HCP-MMP1.annot"
    if not lh_path.exists() or not rh_path.exists():
        raise FileNotFoundError(
            "HCP MMP1.0 annotation files not found. Expected atlases/lh.HCP-MMP1.annot and atlases/rh.HCP-MMP1.annot"
        )

    labels_lh, _, names_lh_raw = nib.freesurfer.read_annot(str(lh_path))
    labels_rh, _, names_rh_raw = nib.freesurfer.read_annot(str(rh_path))
    names_lh = _decode(names_lh_raw)
    names_rh = _decode(names_rh_raw)

    atlas_labels_path = atlas_dir / "atlas_labels.txt"
    with atlas_labels_path.open("w", encoding="utf-8") as handle:
        handle.write("LEFT HEMISPHERE:\n")
        for idx, name in enumerate(names_lh):
            handle.write(f"  Index {idx}: {name}\n")
        handle.write("\nRIGHT HEMISPHERE:\n")
        for idx, name in enumerate(names_rh):
            handle.write(f"  Index {idx}: {name}\n")

    all_found = True
    for dim_name, hemis in REQUIRED_AREAS.items():
        for hemi, areas in hemis.items():
            label_names = names_lh if hemi == "left" else names_rh
            labels = labels_lh if hemi == "left" else labels_rh
            for area in areas:
                candidates = _candidates(area, hemi)
                found = False
                for candidate in candidates:
                    if candidate in label_names:
                        idx = label_names.index(candidate)
                        _ = int((labels == idx).sum())
                        found = True
                        break
                if not found:
                    logger.error("Missing area dim=%s hemi=%s area=%s", dim_name, hemi, area)
                    all_found = False

    assert all_found, "Some required atlas areas are missing. Check logs."

