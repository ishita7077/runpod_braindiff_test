# 04 — Circular Dependencies

**Agent:** 4/8 ("VibeCode Cleanser")
**Branch:** `cleanup/vibecode-cleanse`
**Scope:** `backend/` (21 modules), with cross-edges into `tests/` and `scripts/`

## TL;DR

**No circular imports.** Graph is strictly layered: `api` sits on top, depends on everything;
every other module is either a leaf or has a single downward edge. The two deferred
(inside-function) imports are clean — they lazy-load heavy modules, they do **not**
hide any underlying cycle.

No code changes made. Phase 3 skipped per task spec.

---

## 1. Import Graph

Only intra-`backend` edges shown (stdlib/third-party omitted). Directed: caller → callee.

```
                           ┌────────────────────── api ─────────────────────────┐
                           │  (top layer; FastAPI app; imports 16 siblings)     │
                           └───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┬───┘
                               │   │   │   │   │   │   │   │   │   │   │   │
          ┌────────────────────┘   │   │   │   │   │   │   │   │   │   │   └─────────────────┐
          ▼                        ▼   ▼   ▼   ▼   ▼   ▼   ▼   ▼   ▼   ▼                     ▼
   model_service            atlas_peaks  heatmap  differ  narrative  insight_engine   result_semantics
          │                        ┊(lazy)   │       │        │           │                  │
          ├──► neuralset_mps_patch ┊         │       │        │           │                  │
          └──► runtime             ┊         ▼       ▼        ▼           ▼                  ▼
                                   ┊       scorer (leaf)                                    (leaf)
                                   ┊
                           brain_regions (leaf)

   Other leaves (imported only by api or tests):
     schemas, scorer, status_store, telemetry_store, startup_manifest,
     logging_utils, preflight, vertex_codec, brain_regions, brain_mesh
   Orphans:
     __init__.py (empty package marker)

   Deferred (inside-function) edges:
     atlas_peaks._label_arrays()  ┈┈► brain_regions          (lazy — see §3.a)
     api.brain_mesh() endpoint    ┈┈► brain_mesh             (lazy — see §3.b)

   Cross-package edges:
     tests/* ──► backend.{api, differ, scorer, preflight, insight_engine,
                           heatmap, brain_regions, telemetry_store,
                           model_service, runtime}
     scripts/preview_server.py ──► backend.{brain_mesh, schemas}
     scripts/preflight.sh (heredoc) ──► backend.{brain_regions, model_service, preflight}
```

### Edge inventory (module-level, eager)

| Source module       | Imports (backend.*)                                                                                                                                                                |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `api`               | `atlas_peaks`, `brain_regions`, `differ`, `heatmap`, `logging_utils`, `model_service`, `narrative`, `preflight`, `result_semantics`, `insight_engine`, `schemas`, `scorer`, `startup_manifest`, `status_store`, `telemetry_store`, `vertex_codec` |
| `heatmap`           | `scorer`                                                                                                                                                                           |
| `model_service`     | `neuralset_mps_patch`, `runtime`                                                                                                                                                   |
| *all others*        | *(none — no intra-backend imports)*                                                                                                                                                |

Total internal edges: **19** eager + **2** deferred = **21**.

### Layering

Implied layers, bottom-up:

1. **Leaves (no intra-backend deps):** `schemas`, `status_store`, `telemetry_store`, `vertex_codec`, `logging_utils`, `startup_manifest`, `preflight`, `narrative`, `result_semantics`, `insight_engine`, `differ`, `brain_regions`, `brain_mesh`, `runtime`, `neuralset_mps_patch`, `scorer`, `atlas_peaks` *(top-level-wise; its sole backend dep is lazy)*
2. **Mid:** `heatmap` (→ scorer), `model_service` (→ neuralset_mps_patch, runtime)
3. **Top:** `api`

Flow direction matches the expected layering (`schemas < storage < services < api`). Nothing crosses layers upward.

---

## 2. Cycles Found

**Zero.** Manually walked every edge; the graph is a DAG rooted at `api`.

Verification: the only module with in-degree > 1 from `backend` is `scorer` (api, heatmap)
and `brain_regions` (api, atlas_peaks — lazy). Neither `scorer` nor `brain_regions`
imports anything in `backend`, so no cycle can close.

---

## 3. Deferred / Late Imports

Two found. Both are **benign lazy loads**, not cycle workarounds.

### a) `backend/atlas_peaks.py:20` — inside `_label_arrays()`

```20:26:backend/atlas_peaks.py
    from backend.brain_regions import _downsample_labels_to_fsaverage5, load_hcp_annotations

    labels_lh, labels_rh, names_lh, names_rh = load_hcp_annotations(atlas_dir)
    labels_lh = _downsample_labels_to_fsaverage5(labels_lh, "left", atlas_dir)
    labels_rh = _downsample_labels_to_fsaverage5(labels_rh, "right", atlas_dir)
    _CACHE = (labels_lh, labels_rh, names_lh, names_rh)
    return _CACHE
```

**Why deferred:** `brain_regions` pulls numpy + atlas annotation files; module is cached
after first successful load via `_CACHE`. Keeps `atlas_peaks` importable on machines
without atlas data installed (peak description just returns `None` on failure).

**Underlying cycle?** No. `brain_regions` imports nothing from `atlas_peaks`.

**Action:** leave as-is.

### b) `backend/api.py:550` — inside `brain_mesh` endpoint

```547:552:backend/api.py
@app.get("/api/brain-mesh")
async def brain_mesh() -> JSONResponse:
    """fsaverage5 pial coordinates for left/right hemispheres (WebGL viewer)."""
    from backend.brain_mesh import build_brain_mesh_payload

    return JSONResponse(build_brain_mesh_payload())
```

**Why deferred:** defers reading the fsaverage5 mesh files until the endpoint is
actually hit, so startup doesn't touch disk for a rarely-used viewer route.

**Underlying cycle?** No. `brain_mesh` imports only stdlib + numpy.

**Action:** leave as-is. Could be promoted to a top-level import for consistency,
but that trades startup latency for uniformity — not worth it. Flagging only.

---

## 4. Proposed Fixes

N/A. No cycles to fix.

If cycles ever appear, the natural break points based on current layering would be:

- Extract pure-data helpers shared by `scorer`/`heatmap` into `schemas` or a new `metrics_types` module.
- Keep `brain_regions` and `atlas_peaks` independent; if they ever grow mutual deps,
  pull the shared annotation-loader into `brain_regions` (already the owner of those helpers).

## 5. Confidence

- **"No cycles exist":** HIGH. Small graph (21 edges total), manually verified.
- **"Deferred imports are benign lazy loads, not cycle camouflage":** HIGH. Confirmed by
  reading both call sites and their targets' import tables.

---

## 6. Sanity checks run

```
$ python3 -m py_compile backend/*.py        → OK
$ python3 -m py_compile tests/*.py          → OK
$ python3 --version                         → Python 3.9.6
```

Attempting to actually import most backend modules fails on this machine for reasons
**unrelated to cycles:**

- `matplotlib`/`numpy`/`pydantic`/`fastapi` not installed in system Python.
- Several modules use PEP 604 unions (`str | None`) which require Python 3.10+; system
  Python here is 3.9.6. Example: `backend/status_store.py:23`. This is a pre-existing
  runtime-target constraint (see `requirements_frozen.txt` / CI config), not a cycle,
  and not in scope for this pass.

Both are expected per task brief; no action taken.

---

## 7. Files modified

None.
