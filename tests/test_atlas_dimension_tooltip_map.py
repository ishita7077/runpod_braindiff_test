"""Ensure HCP label strings (e.g. L_46_ROI) resolve to Brain Diff dimensions for tooltips."""

from backend.brain_regions import REQUIRED_AREAS, _candidates


def _build_dim_map_like_atlas_peaks() -> dict[str, list[str]]:
    dim_map: dict[str, list[str]] = {}
    for dim_name, hemis in REQUIRED_AREAS.items():
        for hemi, areas in hemis.items():
            for area in areas:
                for cand in _candidates(area, hemi):
                    dim_map.setdefault(cand, [])
                    if dim_name not in dim_map[cand]:
                        dim_map[cand].append(dim_name)
    return dim_map


def test_dimension_map_includes_l_roi_style_keys() -> None:
    m = _build_dim_map_like_atlas_peaks()
    assert "L_46_ROI" in m
    assert "brain_effort" in m["L_46_ROI"]
    assert "R_PGi_ROI" in m
    assert "social_thinking" in m["R_PGi_ROI"]
