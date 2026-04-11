import numpy as np

from backend.heatmap import compute_vertex_delta


def test_vertex_delta_uses_signed_difference() -> None:
    a = np.zeros((4, 20484), dtype=np.float32)
    b = np.zeros((4, 20484), dtype=np.float32)
    a[:, :10] = -1.0
    b[:, :10] = 2.0
    delta, norm_a, norm_b = compute_vertex_delta(a, b)
    assert delta.shape == (20484,)
    assert norm_a.shape == (20484,)
    assert norm_b.shape == (20484,)
    assert np.all(delta[:10] > 0)
    assert np.allclose(delta[100:110], 0.0)
    assert np.all(norm_a[:10] < 0)
    assert np.all(norm_b[:10] > 0)
