from pathlib import Path
import logging
import base64
import io
from typing import Any

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

from backend.scorer import reference_scale

logger = logging.getLogger("braindiff.heatmap")

_FSAVERAGE = None

# Muted diverging map (easier on the eyes than raw matplotlib "bwr" on OLED black).
_SOFT_DIVERGING = LinearSegmentedColormap.from_list(
    "braindiff_soft_div",
    ["#1e3555", "#4a6288", "#9aa3b0", "#e4e2de", "#c4a398", "#8f4d52", "#5c2f38"],
    N=256,
)


def _get_fsaverage():
    global _FSAVERAGE
    if _FSAVERAGE is None:
        from nilearn import datasets

        data_dir = str(Path("atlases/nilearn_data").resolve()) if Path("atlases/nilearn_data").exists() else None
        _FSAVERAGE = datasets.fetch_surf_fsaverage(mesh="fsaverage5", data_dir=data_dir)
    return _FSAVERAGE


def compute_vertex_delta(
    preds_a: np.ndarray, preds_b: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (delta, norm_a, norm_b) where delta = norm_b - norm_a."""
    if preds_a.shape[1] != 20484 or preds_b.shape[1] != 20484:
        raise ValueError(f"Vertex mismatch: A={preds_a.shape}, B={preds_b.shape}")
    norm_a = preds_a.mean(axis=0) / reference_scale(preds_a)
    norm_b = preds_b.mean(axis=0) / reference_scale(preds_b)
    return norm_b - norm_a, norm_a, norm_b


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

    _bg = "#0a0c10"
    fig = plt.figure(figsize=(13, 7), dpi=180, facecolor=_bg)
    axes = [fig.add_subplot(2, 2, i + 1, projection="3d") for i in range(4)]
    view_labels = ["Left lateral", "Right lateral", "Left medial", "Right medial"]
    views = [
        ("left", "lateral", fsavg.pial_left, fsavg.sulc_left, lh),
        ("right", "lateral", fsavg.pial_right, fsavg.sulc_right, rh),
        ("left", "medial", fsavg.pial_left, fsavg.sulc_left, lh),
        ("right", "medial", fsavg.pial_right, fsavg.sulc_right, rh),
    ]
    for ax, (hemi, view, mesh, bg, data), vlabel in zip(axes, views, view_labels):
        plotting.plot_surf_stat_map(
            surf_mesh=mesh,
            stat_map=data,
            hemi=hemi,
            view=view,
            bg_map=bg,
            cmap=_SOFT_DIVERGING,
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
        ax.set_title(vlabel, color="#9aa3ad", fontsize=9, pad=4)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.xaxis.pane.fill = False
        ax.yaxis.pane.fill = False
        ax.zaxis.pane.fill = False
        ax.set_axis_off()

    fig.text(
        0.5,
        0.01,
        "Population-level model contrast (TRIBEv2): warmer = Version B higher · cooler = Version A higher · not medical imaging",
        ha="center",
        color="#7d8692",
        fontsize=8.5,
    )
    fig.subplots_adjust(wspace=0.02, hspace=0.06, bottom=0.06, top=0.95)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=_bg, edgecolor="none", pad_inches=0.08)
    plt.close(fig)

    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "format": "png_base64",
        "image_base64": encoded,
    }
