from pathlib import Path
import logging
import base64
import io
from typing import Any

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.scorer import reference_scale

logger = logging.getLogger("braindiff.heatmap")

_FSAVERAGE = None


def _get_fsaverage():
    global _FSAVERAGE
    if _FSAVERAGE is None:
        from nilearn import datasets

        data_dir = str(Path("atlases/nilearn_data").resolve()) if Path("atlases/nilearn_data").exists() else None
        _FSAVERAGE = datasets.fetch_surf_fsaverage(mesh="fsaverage5", data_dir=data_dir)
    return _FSAVERAGE


def compute_vertex_delta(preds_a: np.ndarray, preds_b: np.ndarray) -> np.ndarray:
    if preds_a.shape[1] != 20484 or preds_b.shape[1] != 20484:
        raise ValueError(f"Vertex mismatch: A={preds_a.shape}, B={preds_b.shape}")
    norm_a = preds_a.mean(axis=0) / reference_scale(preds_a)
    norm_b = preds_b.mean(axis=0) / reference_scale(preds_b)
    return norm_b - norm_a


def generate_heatmap_artifact(vertex_delta: np.ndarray) -> dict[str, Any]:
    from nilearn import plotting

    logger.info("generate_heatmap_artifact:start vertex_len=%s", len(vertex_delta))
    if vertex_delta.shape[0] != 20484:
        raise ValueError(f"Expected 20484 vertex values, got {vertex_delta.shape[0]}")

    fsavg = _get_fsaverage()
    lh = vertex_delta[:10242]
    rh = vertex_delta[10242:]
    vmax = float(np.percentile(np.abs(vertex_delta), 98))
    vmax = max(vmax, 1e-6)

    # Dark figure (matches Tribe-style Web UI); coolwarm still reads on black.
    _bg = "#07080b"
    fig = plt.figure(figsize=(12, 7), dpi=150, facecolor=_bg)
    axes = [fig.add_subplot(2, 2, i + 1, projection="3d") for i in range(4)]
    views = [
        ("left", "lateral", fsavg.pial_left, fsavg.sulc_left, lh),
        ("right", "lateral", fsavg.pial_right, fsavg.sulc_right, rh),
        ("left", "medial", fsavg.pial_left, fsavg.sulc_left, lh),
        ("right", "dorsal", fsavg.pial_right, fsavg.sulc_right, rh),
    ]
    for ax, (hemi, view, mesh, bg, data) in zip(axes, views):
        plotting.plot_surf_stat_map(
            surf_mesh=mesh,
            stat_map=data,
            hemi=hemi,
            view=view,
            bg_map=bg,
            cmap="coolwarm",
            symmetric_cbar=True,
            threshold=0.0,
            colorbar=False,
            vmax=vmax,
            axes=ax,
        )
        try:
            ax.set_facecolor(_bg)
        except Exception:
            pass
        ax.set_title(f"{hemi.title()} {view}", color="0.85", fontsize=9)
        ax.xaxis.pane.fill = False
        ax.yaxis.pane.fill = False
        ax.zaxis.pane.fill = False
        ax.tick_params(colors="0.5", labelsize=6)

    fig.suptitle(
        "Brain activation difference: red = Version B higher, blue = Version A higher",
        color="0.92",
        fontsize=11,
    )
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)

    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "format": "png_base64",
        "image_base64": encoded,
    }
