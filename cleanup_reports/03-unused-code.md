# Agent 3 — Unused code (knip-style dead-code pass)

Scope: find code symbols, constants, files, and API routes that are defined
but never referenced anywhere in the runtime codebase. Cross-checked against
backend Python, `frontend_new/` HTML+JS, tests, scripts, and shell tooling.

Agent 7 already removed the legacy `frontend/` and `frontend 2/` trees and two
small dead branches (`DESTRIEUX_FALLBACK` in `brain_regions.py`, a 2-tuple
branch in `_coerce_prediction_output`). This pass starts from that state.

## 1. Methodology

- Read every `.py` file in `backend/`, `tests/`, `scripts/` end-to-end.
- Enumerated every `def` / `class` / module-level constant / Pydantic model,
  and every FastAPI route.
- For every candidate, grepped the *entire* repo (excluding `.git/`,
  `atlases/`, `third_party/`, and `cleanup_reports/`) for:
  - the bare name (function / class / constant)
  - the import path (`from backend.X import Y`)
  - the URL (for FastAPI routes: `fetch('/api/...')`, `client.get(...)`,
    `_req('GET', '/api/...')`, etc.)
  - attribute/string access that could call a thing by name
- Ran `vulture backend/ tests/ scripts/ --min-confidence 60` as a sanity
  cross-check (vulture install done via a one-shot `venv`, since the host
  pip refuses modern installs). All 60%-confidence "unused function" hits
  from vulture were FastAPI route handlers — those are live via URL and not
  dead code.
- Did *not* try to run `knip` on the frontend: it's pure HTML+inline JS with
  no module system and vanilla `fetch`, so a static analyzer would produce
  too many false positives. Verified frontend usage by greping each HTML
  file for `fetch(`, `href=`, `getElementById(`, and `querySelector(`.

Tools used: `ripgrep`, `vulture 2.16`, `python3 -m py_compile`.

## 2. Findings

### 2.1 HIGH confidence (truly zero references, safe to delete)

| Symbol / route | File | Why it's dead | Grep that proves it |
|---|---|---|---|
| `@app.get("/api/diff/status/{job_id}/stream")` → `diff_status_stream` | `backend/api.py:441-460` | SSE variant of the status endpoint. `frontend_new/run.html` polls `/api/diff/status/{id}` every ~250 ms and never opens an `EventSource`. No test or script hits `/stream`. | `rg "/stream"` → only the route def itself, plus the matching mock in preview_server (also dead). `rg "EventSource"` → 0 hits in `frontend_new/`. |
| `@app.get("/api/vertex-atlas")` → `vertex_atlas` | `backend/api.py:578-583` | Endpoint intended for hover tooltips, but no hover code in `frontend_new/` calls it. Not in tests, not in scripts. | `rg "/api/vertex-atlas"` → only the route def. `rg "vertex-atlas"` → only the route def. |
| `build_vertex_atlas_payload(...)` + module-level `_ATLAS_PAYLOAD` cache | `backend/atlas_peaks.py:14, 68-98` | Only caller is the removed `/api/vertex-atlas` route (imported lazily). The helpers it pulls in (`REQUIRED_AREAS`, `_candidates`) stay because `test_atlas_dimension_tooltip_map.py` reuses them directly. | `rg "build_vertex_atlas_payload"` → only its definition + the now-dead route. |
| `@app.get("/api/diff/status/{job_id}/stream")` → `mock_diff_stream` | `scripts/preview_server.py:205-220` | Mock pair of the dead real-stream route. Docstring even says "so run.html can keep listening *if* it tries the stream variant"; run.html does not. | Same greps as above — 0 fetch/EventSource hits. |
| `import json` | `backend/api.py:4` | Only used inside `diff_status_stream` (`json.dumps(event)`). Dead after that route is removed. | `rg "\\bjson\\b" backend/api.py` → only the stream route + an unrelated string `"backend/startup_manifest.json"` (path literal, not a module use). |
| `StreamingResponse` import | `backend/api.py:14`, `scripts/preview_server.py:40` | Only used by the two removed stream endpoints. | `rg "StreamingResponse"` in each file → just the removed route returns. |

Total HIGH removals: 4 code units + 2 redundant imports, ≈75 lines.

### 2.2 MEDIUM confidence (likely unused, but plausible external use — deferred)

| Symbol / route | File | Why it *might* still matter |
|---|---|---|
| `@app.get("/api/health")` → `health` | `backend/api.py:540-542` | Trivial alias that calls `api_ready()`. No internal caller (tests hit `/api/ready`, e2e script hits `/api/ready`). But `/api/health` is a near-universal convention for container/uptime checks. Removing it could silently break a prod docker-healthcheck. Deferred to the user. |
| `@app.get("/api/health")` mock | `scripts/preview_server.py:75-77` | Same deal in the dev preview server. Dead in-repo but cheap to keep while `/api/health` exists in the real backend. |
| `@app.post("/api/report")` → `report_batch` + `_compute_report_summary` + `ReportPair` + `ReportRequest` | `backend/api.py:59-81, 479-514`; `backend/schemas.py:15-22` | No frontend or script uses `/api/report`. Only `tests/test_api.py` exercises it (3 tests). That's "tested but unused in product" — it may be a future batch-mode feature, or it may be a shipped-then-forgotten endpoint. Deferring so the user decides. |
| `@app.post("/api/diff")` → `diff_sync` | `backend/api.py:463-476` | The live UI only uses the async `start`/`status` flow. Agent 7 already flagged this; I'm carrying the flag forward. Tests rely on it, so deleting it is a bigger change. |

### 2.3 LOW confidence (suspicious, leave alone)

| Symbol | File | Why not to remove |
|---|---|---|
| `PLAIN_NAMES` dict + fallback branch | `backend/narrative.py:3-11, 54-57` | All current dimensions have `DISCOVERY_HEADLINES` entries, so `PLAIN_NAMES` is technically unreachable in today's tree. Agent 7 kept it as a defensive fallback for future dimensions. Leaving per the same rationale. |
| `text_path` parameter in mock `get_events_dataframe` / `args` in `from_pretrained` | `tests/test_model_smoke.py:39, 47` | Vulture 100%-confidence hits, but they are *required* to match TRIBEv2's real API signature — pytest would break if we drop them. Not dead. |
| `_FSAVERAGE` (heatmap), `_CACHE` (atlas_peaks), `_brainMeshPromise` caches | various | Module-level memoization caches, set and read inside the module. Look "unused" at import time but are live. |

### 2.4 Pre-existing issues noticed (NOT fixed here — flagging for owner)

Not unused-code bugs, but spotted during the grep pass. Leaving them for the
user / subsequent agent to fix:

1. **`tests/test_status_flow.py`** — the `_DummyTribeService.text_to_predictions`
   returns a 2-tuple (`return base, []`). After Agent 7 collapsed
   `_coerce_prediction_output` to the 3-tuple-only path, this test will raise
   `ValueError: Unexpected prediction output shape: tuple`. Needs to be
   updated to `return base, [], {"events_ms": 1, "predict_ms": 2}` the same
   way `test_api.py` and `test_telemetry.py` already do.
2. **`tests/test_masks_nonzero.py`** — asserts the masks dict has exactly 6
   keys, but `brain_regions.DIMENSIONS_HCP` now defines 7 (added
   `attention_salience`). Test will fail on any env with the atlas present.
3. **`backend/api.py:170-175`** — five blank lines between the `FastAPI` app
   construction and the next helper. Cosmetic cruft, not removed in this
   pass to keep the diff focused.

## 3. Removal plan (HIGH confidence, executed)

### 3.1 `backend/api.py`
- Drop `import json` (line 4) — only used by the stream route being removed.
- Remove `StreamingResponse` from the `fastapi.responses` import on line 14.
- Delete the whole `@app.get("/api/diff/status/{job_id}/stream")` block
  (lines 441-460, 20 lines).
- Delete the `@app.get("/api/vertex-atlas")` block (lines 578-583, 6 lines).

### 3.2 `backend/atlas_peaks.py`
- Delete the `_ATLAS_PAYLOAD` global (line 14).
- Delete `build_vertex_atlas_payload(...)` (lines 68-98, 31 lines).
- Keep `_label_arrays`, `_CACHE`, and `describe_peak_abs_delta` (all used by
  the live `/api/diff` pipeline via `api.py` line 17).

### 3.3 `scripts/preview_server.py`
- Remove `StreamingResponse` from the `fastapi.responses` import on line 40.
- Delete the `@app.get("/api/diff/status/{job_id}/stream")` mock block
  (lines 205-220, 16 lines).

No changes to tests, schemas, frontend HTML, or shell scripts in this pass.

## 4. Sanity checks after edits

- `python3 -m py_compile backend/*.py tests/*.py scripts/*.py` → (see final
  report in the parent summary)
- `rg "json\\." backend/api.py` → no hits (confirming `import json` removal
  is safe)
- `rg "StreamingResponse" backend/ scripts/` → no hits after edits
- `rg "build_vertex_atlas_payload|_ATLAS_PAYLOAD|/api/vertex-atlas|/api/diff/status/.*stream"` → no hits after edits

## 5. Deferred / flagged for user review

- `/api/health` (real + preview) — MEDIUM. Keep unless you confirm no
  monitoring/docker health-check hits it.
- `/api/report` + `_compute_report_summary` + `ReportPair` + `ReportRequest`
  — MEDIUM. Only lives in tests; decide whether this is a shipped feature
  or a forgotten prototype.
- `/api/diff` sync endpoint — MEDIUM (already flagged by Agent 7).
- `PLAIN_NAMES` defensive fallback in `narrative.py` — LOW.
- `test_status_flow.py` and `test_masks_nonzero.py` pre-existing drift —
  not dead code, needs a fixup commit.
- 5 blank lines in `backend/api.py` around line 170 — cosmetic.
