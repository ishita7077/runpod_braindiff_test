import numpy as np

from backend.heatmap import compute_vertex_delta


def test_vertex_delta_uses_signed_difference() -> None:
    a = np.zeros((4, 20484), dtype=np.float32)
    b = np.zeros((4, 20484), dtype=np.float32)
    a[:, :10] = -1.0
    b[:, :10] = 2.0
    delta = compute_vertex_delta(a, b)
    assert delta.shape == (20484,)
    assert np.allclose(delta[:10], 3.0)
    assert np.allclose(delta[100:110], 0.0)

