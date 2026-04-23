import pytest
pytest.importorskip("nibabel")

from backend.brain_regions import build_vertex_masks


def test_all_dimension_masks_are_nonzero() -> None:
    masks = build_vertex_masks("atlases")
    assert set(masks.keys()) == {
        "personal_resonance",
        "social_thinking",
        "brain_effort",
        "language_depth",
        "gut_reaction",
        "memory_encoding",
        "attention_salience",
    }
    for dim_name, dim_data in masks.items():
        assert int(dim_data["mask"].sum()) > 0, f"{dim_name} mask has zero vertices"
