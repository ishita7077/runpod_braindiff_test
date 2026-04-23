import logging
from pathlib import Path

import pytest
nib = pytest.importorskip("nibabel")

from backend.brain_regions import REQUIRED_AREAS, _candidates, _decode_names

logger = logging.getLogger("braindiff.test_atlas_labels")


def test_atlas_loads_and_contains_all_areas() -> None:
    atlas_dir = Path("atlases")
    lh_path = atlas_dir / "lh.HCP-MMP1.annot"
    rh_path = atlas_dir / "rh.HCP-MMP1.annot"
    labels_lh, _, names_lh_raw = nib.freesurfer.read_annot(str(lh_path))
    labels_rh, _, names_rh_raw = nib.freesurfer.read_annot(str(rh_path))
    names_lh = _decode_names(names_lh_raw)
    names_rh = _decode_names(names_rh_raw)
    all_found = True
    for dim_name, hemis in REQUIRED_AREAS.items():
        for hemi, areas in hemis.items():
            label_names = names_lh if hemi == "left" else names_rh
            labels = labels_lh if hemi == "left" else labels_rh
            for area in areas:
                found = False
                for candidate in _candidates(area, hemi):
                    if candidate in label_names:
                        idx = label_names.index(candidate)
                        _ = int((labels == idx).sum())
                        found = True
                        break
                if not found:
                    logger.error("Missing area dim=%s hemi=%s area=%s", dim_name, hemi, area)
                    all_found = False
    assert all_found
