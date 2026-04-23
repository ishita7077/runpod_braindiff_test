# Agent 1 — Deduplicate / DRY

**Branch:** `cleanup/vibecode-cleanse`
**Scope:** `backend/` (21 modules), `frontend_new/` (6 HTML pages), `tests/`, `scripts/`
**Prior agents completed before this pass:** 7 (legacy/fallback), 3 (unused code),
4 (circular deps — no changes). I started from their state.

Principle: DRY only where it reduces complexity. Prefer a small helper over
copy-paste; never invent a factory/dispatcher just to hide repetition; never
couple unrelated layers just because they share a keyword.

## 1. Duplication map

| # | Duplication | Files / lines | Nature | Recommendation | Confidence |
|---|---|---|---|---|---|
| 1 | `runtime_dict = {"device": profile.device, "backend": profile.backend}` with `None` guard | `backend/api.py` — 4 sites: `_get_diff_semaphore`, `_initialize_app`, `_persist_run`, `/api/preflight`, `/api/ready` | 4× 5-line identical block reading `tribe_service.runtime_profile` | EXTRACT → `backend/runtime.py:runtime_to_dict(profile)` + tiny `api._service_runtime_dict()` wrapper | HIGH |
| 2 | Result-dict construction for `/api/diff` | `backend/api.py` lines ~256-289 (short-circuit branch) and ~339-371 (normal branch) in `_run_diff_job` | Two ~35-line dicts differ only in `identical_text_short_circuit`, `text_*_timesteps`, `median_a/b`. Both call `build_insight_payload` with the same tone lookup. | EXTRACT → `api._build_diff_result(...)` + `api._narrative_tone()` | HIGH |
| 3 | Dead `if (false) (function(){ … })();` polling IIFE | `frontend_new/run.html:1632-1890` (262 lines) | Second copy of `pollOnce` / `showError` / `ERROR_TIPS` / `completionSequence` / `applyStatus`, wrapped in an `if (false)` guard so it never runs. An explicit comment above it says the polling logic moved to the separate `<script>` tag higher in the file. | MERGE — delete the dead copy, keep the one that actually runs | HIGH |
| 4 | `_DummyTribeService` class + `_dummy_masks()` helper | `tests/test_api.py:13-38`, `tests/test_telemetry.py:9-33`, `tests/test_status_flow.py:9-32` | 3 near-identical definitions. test_api / test_telemetry diverge only in `events_ms` / `predict_ms` / `backend` fields; test_status_flow returns a broken 2-tuple (pre-existing bug flagged by Agent 3, left alone). | EXTRACT → `tests/conftest.py:DummyTribeService(runtime_backend=, events_ms=, predict_ms=)` + `dummy_masks()` | HIGH for test_api / test_telemetry; SKIP test_status_flow (different broken signature, not this agent's fix) |
| 5 | Common `monkeypatch` incantation for `/api/*` tests | `tests/test_api.py` 15 call sites set `BRAIN_DIFF_SKIP_STARTUP=1` + stub `tribe_service` / `masks` / `generate_heatmap_artifact` in the same order | ~5 lines repeated each time | EXTRACT → `tests/conftest.py:apply_api_test_stubs(monkeypatch, api, *, tribe_service=None, masks=None, stub_heatmap=True, skip_startup=True)` | HIGH |
| 6 | `os.getenv("BRAIN_DIFF_ATLAS_DIR", "atlases")` | `backend/api.py:128,151,561`, `backend/atlas_peaks.py:31` | 4 identical one-liners | IGNORE — extracting a helper only turns 40 chars into a function call, zero real saving | LOW |
| 7 | `base64.b64encode(x).decode("ascii")` | `backend/api.py:570` (uint8 masks), `backend/heatmap.py:111` (PNG bytes), `backend/vertex_codec.py:13` (float32) | 3 sites, different inputs | IGNORE — one-liner, different types. `vertex_codec.f32_b64` already covers the float32 case; adding `u8_b64` would save one line. | LOW |
| 8 | Two `_strength_label(magnitude)` functions | `backend/result_semantics.py:34` vs `backend/insight_engine.py:111` | Same name, **different thresholds + labels** (0.005/0.02/0.06/0.14 "Very small…" vs 0.015/0.05/0.12/0.22 "Minimal…") | IGNORE — DRY here would couple two independent narrative layers that deliberately slice magnitudes differently | HIGH confidence to leave |
| 9 | Per-dimension metadata spread across modules: `brain_regions.DIMENSIONS_HCP`, `result_semantics.UI_LABELS/TOOLTIPS/USER_MEANING`, `narrative.PLAIN_NAMES/DISCOVERY_HEADLINES`, `insight_engine.DIMENSION_FRAMING/DISCOVERY_TEMPLATES` | 5 modules, 7 dicts all keyed on the same 7 dim names | Separate concerns (atlas ROIs vs UI copy vs narrative templates vs discovery text). | IGNORE — merging would collapse layers for no net gain; drift risk on a new dim is mitigated by tests per file | HIGH confidence to leave |
| 10 | `narrative.PLAIN_NAMES` vs `result_semantics.UI_LABELS` (lowercased) | `backend/narrative.py:3-11` | Almost but not exactly `UI_LABELS[k].lower()` (`"attention"` vs `"Attention"` / `"Personal Resonance"` → `"personal resonance"`, same shape) | IGNORE — Agents 3 and 7 flagged `PLAIN_NAMES` as a defensive fallback never reached today; touching it now widens the change for no behavioural gain | LOW |
| 11 | `_page(name)` + `page_research/methodology/launch` routes | `backend/api.py:596-613` and `scripts/preview_server.py:51-67` | Identical FastAPI handlers in the live backend and the mock preview server | IGNORE — two separate ASGI apps; sharing would force `scripts/preview_server` to import a helper that transitively loads the full backend (the whole point of the preview server is to boot without TRIBEv2/WhisperX/Llama) | HIGH confidence to leave |
| 12 | `REQUIRED_AREAS` + `_decode`/`_candidates` in `tests/test_atlas_labels.py:10-27` | `tests/test_atlas_labels.py` vs `backend/brain_regions.py` (already exported) | Test redefines the dict (missing `attention_salience`) and candidate enumerator. | IGNORE for now — dropping the local copy would flip the test from 6-dim to 7-dim coverage. Agent 3 noted a related pre-existing drift (`test_masks_nonzero` expects 6 keys, backend has 7); a unified atlas-test fix belongs to a dedicated correctness pass, not a dedup pass. | MEDIUM — deferred |
| 13 | `fetch('/api/brain-mesh', { cache: 'force-cache' })` | `frontend_new/run.html:1364`, `frontend_new/results.html:1268`, `frontend_new/index.html:1237` | 3 call sites in 3 independent inline scripts (two are `<script type="module">`, one a classic IIFE) | IGNORE — extracting to `frontend_new/shared.js` would introduce a load-order dependency and a global for 3 × 3-line fetches; that's over-DRY | MEDIUM confidence to leave |
| 14 | `fetch('/api/diff/status/' + encodeURIComponent(JOB_ID))` polling loop | `frontend_new/run.html:1233` (real) and `frontend_new/results.html:1261` (one-shot) | Two separate shapes — run.html runs a repeating timer with step/status updates; results.html does one fetch then bails to `/run.html` if not done | IGNORE — different concerns, different lifetimes, extraction would add a helper with a large option surface | HIGH confidence to leave |
| 15 | `TribeService._ensure_uvx_on_path` / `_ensure_ffmpeg_on_path` vs `preflight.check_uvx` / `check_ffmpeg` | `backend/model_service.py:190-224` vs `backend/preflight.py:7-49` | One side mutates PATH (boot), other side reads PATH (probe) | IGNORE — different purposes despite similar surface | HIGH confidence to leave |

Estimated net line savings from HIGH-confidence items: ~−340 lines.

## 2. Consolidations implemented

### Backend

1. **`backend/runtime.py`** — new helper `runtime_to_dict(profile) -> dict`
   turns an optional `RuntimeProfile` into the `{device, backend}` snapshot
   used by `/api/ready`, `/api/preflight`, telemetry, and the startup
   manifest. 8 lines added.

2. **`backend/api.py`**
   - Added `_service_runtime_dict()` 1-line wrapper around `runtime_to_dict`
     that reads the live `tribe_service.runtime_profile`.
   - Replaced 4 inline `runtime_dict = {...}` blocks (1 in
     `_get_diff_semaphore`, 1 in `_initialize_app`, 1 in `_persist_run`, 1 in
     `/api/preflight`, 1 in `/api/ready`) with `_service_runtime_dict()`.
   - Added `_narrative_tone()` helper (the `BRAIN_DIFF_NARRATIVE_TONE`
     lookup, previously duplicated in the two `_run_diff_job` branches).
   - Added `_build_diff_result(**kwargs)` helper that assembles the full
     `/api/diff` response body (`diff / dimensions / insights /
     vertex_*_b64 / warnings / meta`). Both branches of `_run_diff_job`
     (identical-text short-circuit and normal pipeline) now call it; the
     `identical_text_short_circuit` flag is set by a single boolean
     parameter.
   - Net: ~−60 lines on `_run_diff_job` without changing any response key,
     ordering of JSON output, or public function signature.

### Frontend

3. **`frontend_new/run.html`** — deleted the 262-line `if (false) (function(){
   … })();` IIFE (lines 1632-1890) that held an old, fully-duplicated copy of
   `pollOnce` / `schedule` / `showError` / `ERROR_TIPS` /
   `completionSequence` / `applyStatus` / `ensureBar` / `setStep` /
   `stepIs` / `setProgressMessage` / `setActiveTime` / `resetSteps`. The
   existing comment above it already stated the real logic had moved to its
   own `<script>` tag. Replaced the whole block with a 3-line comment. No
   runtime behaviour change (the block was gated by `if (false)` and never
   executed).

### Tests

4. **`tests/conftest.py`** — promoted:
   - `DummyTribeService` (parametrized `runtime_backend`, `events_ms`,
     `predict_ms` so one class covers test_api + test_telemetry cleanly)
   - `dummy_masks(extra_keys=...)` (returns the 6-dim default; callers can
     trim, as `tests/test_telemetry.py` does)
   - `apply_api_test_stubs(monkeypatch, api_module, *, tribe_service=None,
     masks=None, stub_heatmap=True, skip_startup=True)` that applies the
     four-step monkeypatch incantation used across `test_api.py`.

5. **`tests/test_api.py`** — every test now routes its setup through
   `apply_api_test_stubs(...)`. Function bodies dropped from ~7-line patch
   blocks to 1-3 lines. Removed local `_DummyTribeService` and
   `_dummy_masks`.

6. **`tests/test_telemetry.py`** — now imports the same shared helpers,
   with a small local `_telemetry_masks()` that trims `memory_encoding`
   from the shared masks to match the original in-file fixture's 5-key
   shape. `events_ms=12, predict_ms=34` parameters on `DummyTribeService`
   preserve the assertion `stage_times["events_a_ms"] == 12`.

7. **`tests/test_status_flow.py`** — intentionally unchanged. Its local
   `_DummyTribeService.text_to_predictions` returns a 2-tuple (a
   pre-existing break Agent 3 flagged); adopting the shared 3-tuple class
   would change its behaviour. That's not a dedup fix.

## 3. Deferred (with reasoning)

- **`test_atlas_labels.py` local `REQUIRED_AREAS` / `_candidates`** —
  importing `backend.brain_regions.REQUIRED_AREAS` would be cleaner but
  flips the test from 6-dim to 7-dim coverage (adds `attention_salience`).
  Belongs in a correctness fix, not this pass.

- **Frontend shared.js** — three `fetch('/api/brain-mesh')` sites across
  run/results/index are each 3-5 lines, sitting inside already-assembled
  module or IIFE scopes. A shared script would add a script tag
  dependency, a global, or a build step, for essentially no behavioural
  win. Not worth it.

- **`/api/health` + `/api/report` routes** — deferred by Agent 3 for
  owner review; I did not touch them.

- **Dimension-metadata consolidation across `brain_regions.py`,
  `result_semantics.py`, `narrative.py`, `insight_engine.py`** — 4
  modules own 7 dicts keyed on the same names. The dicts carry different
  kinds of data (atlas ROIs vs UI labels vs narrative templates vs
  discovery headlines). Merging would cross concerns between scoring,
  display, and narrative layers. Not DRY-worthy.

## 4. Sanity checks

```
$ python3 -m py_compile backend/*.py tests/*.py scripts/*.py
(clean)
```

- All previous public surfaces preserved: no FastAPI route removed,
  renamed, or changed in signature; no import from
  `backend.*` changed; no test file removed; no test function renamed.
- `backend/api.py` response JSON keys unchanged (the two-branch result
  dicts were merged through a helper with identical key set).

## 5. Net line delta

Scoped to files I touched:

```
$ git diff --stat backend/api.py backend/runtime.py \
                  frontend_new/run.html \
                  tests/conftest.py tests/test_api.py tests/test_telemetry.py
 backend/api.py          | 272 ++++++++++++++++++++++----------------
 backend/runtime.py      |   8 ++
 frontend_new/run.html   | 265 +-----------------------------------
 tests/conftest.py       | 102 ++++++++++++++++++
 tests/test_api.py       | 138 +++++---------------
 tests/test_telemetry.py |  46 +++-----
 6 files changed, 279 insertions(+), 552 deletions(-)
```

Net **−273 lines** across my files. Part of the `backend/api.py` diff is
Agent 3's prior stream/vertex-atlas route removal (roughly −35 lines),
so my dedup-only share is approximately **−235 net lines**.

Broken down by category:

| Category | Net |
|---|---|
| Dead JS IIFE in `run.html` | −262 |
| Backend result-dict helper + runtime-dict helper | ~−45 |
| Test conftest consolidation | ~−35 |
| All other changes (imports, tone helper) | ~+5 |

## 6. Anti-patterns I deliberately avoided

- No new `utils.py` grab-bag module.
- No factory / registry / dispatch machinery introduced to hide 3-call-site
  patterns.
- No consolidation of `preview_server.py` ↔ `api.py` routes (would couple
  the fast-boot mock to the heavy ML backend).
- No merging of the two `_strength_label` functions (they carry different
  scales and labels on purpose).
- No cross-layer import from `api.py` into `model_service.py` (kept the
  runtime-dict helper in `runtime.py`, which is the layer that owns
  `RuntimeProfile`).
