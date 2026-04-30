"""One-time export of the real fsaverage5 pial mesh as a static JSON asset.

Why this exists: production frontend is served by Vercel; the Vercel-side
`api/brain-mesh.js` route can't import nilearn / build the mesh on demand.
Without this, the audio/video result pages have to fall back to a procedural
folded geometry whose ~8500 vertices DO NOT correspond to fsaverage5 indices,
so painting `vertex_delta_b64` (a 20484-element array) on it is meaningless.

Run this once locally (or once per nilearn upgrade):
    python3 scripts/export_brain_mesh.py

Output:
    frontend_new/assets/brain-mesh.json   (~1.1 MB, committed to repo)

The Vercel `api/brain-mesh.js` route reads that file and returns it; the
result pages fetch `/api/brain-mesh` and now get a real cortex they can
paint with real per-vertex contrast.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.brain_mesh import build_brain_mesh_payload


def main() -> None:
    out_dir = REPO / "frontend_new" / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "brain-mesh.json"

    payload = build_brain_mesh_payload()
    # Round coordinates to 4 decimal places to keep JSON size sane (~1 MB)
    # without losing visible precision on a 1000 px brain canvas.
    def _round(arr: list[list[float]]) -> list[list[float]]:
        return [[round(c, 4) for c in row] for row in arr]

    rounded = {
        "format": payload["format"],
        "lh_coord": _round(payload["lh_coord"]),
        "lh_faces": payload["lh_faces"],
        "rh_coord": _round(payload["rh_coord"]),
        "rh_faces": payload["rh_faces"],
    }
    out_path.write_text(json.dumps(rounded, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out_path}  ({out_path.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"lh: {len(rounded['lh_coord'])} verts, {len(rounded['lh_faces'])} faces")
    print(f"rh: {len(rounded['rh_coord'])} verts, {len(rounded['rh_faces'])} faces")


if __name__ == "__main__":
    main()
