# Agent 7 — Legacy / fallback cleanup

Scope: find and remove deprecated, legacy, or fallback code so the codebase has
a single, clean path for every concern.

## 1. Summary of findings

Biggest wins live in the top-level folder layout. The project has three
"frontend" directories:

- `frontend_new/` — the live, runtime frontend. Served by `backend/api.py`
  (lines 628, 632, 651) and by `scripts/preview_server.py` (line 48).
- `frontend/` — first shipped UI; replaced.
- `frontend 2/` — later experimental pass (landing-v2 redesign) that was
  itself replaced by `frontend_new/`. Git log confirms the sequence
  (`switch local app to new frontend 2 experience` → `integrate new
  landing/input/run/results UI`).

Neither `frontend/` nor `frontend 2/` is mounted, imported, or requested by the
backend. They are pure git history left on disk.

The only things still pointing at the old `frontend/` folder at runtime are:

- `scripts/validate_loading_facts.py` + `tests/test_loading_facts_json.py` —
  they validate `frontend/data/tribe_loading_facts.json`, which is only
  present in the deleted folders. `frontend_new/` does not reference the
  facts JSON or its URL anywhere, so the validator and its test cover a
  feature that no longer ships.
- `scripts/capture_p1_brain_baselines.sh` — screenshots `/app.html` and
  `/methodology.html`; `frontend_new/` only serves `/launch`, `/methodology`,
  and the `/` landing, so two of five captures 404 today.
- `tests/test_phase_c_contract.py` — asserts on `frontend/index.html`,
  `frontend/app.html`, `frontend/styles.css`, `frontend/app.js`. It will
  start failing the moment we remove the old folder.

Inside `backend/` there is one small dead-code block (`DESTRIEUX_FALLBACK` in
`brain_regions.py`) and one always-true defensive branch in
`api._coerce_prediction_output`. Everything else in `backend/` — the
`fallback_chain` in `runtime.py`, the backend-strategy branches in
`model_service.py`, the MPS/CPU paths in `neuralset_mps_patch.py`, the
`narrative.py` plain-name fallback — is live, exercised fallback and must
stay.

## 2. Inventory

| Item | Evidence it's legacy | Confidence | Action |
|---|---|---|---|
| `frontend/` (whole tree) | Not mounted or imported by `backend/api.py` or `scripts/preview_server.py`; frontend_new/ is the runtime | high | delete |
| `frontend 2/` (whole tree) | Same — later redesign pass, never wired up as runtime | high | delete |
| `frontend/baseline_screenshots/p1-3d/*` and `frontend 2/baseline_screenshots/p1-3d/*` | PNGs captured against URLs (`/app.html`) that no longer exist | high | delete with parent folder |
| `tests/test_phase_c_contract.py` | Asserts on `frontend/index.html` / `frontend/app.html` / `frontend/styles.css` / `frontend/app.js` — all deleted | high | delete |
| `tests/test_loading_facts_json.py` | Points at `frontend/data/tribe_loading_facts.json`; no other `tribe_loading_facts` references exist in `frontend_new/` | high | delete |
| `scripts/validate_loading_facts.py` | Validates only the legacy JSON; its only caller is the test above | high | delete |
| `scripts/capture_p1_brain_baselines.sh` | Targets `/app.html`, `/methodology.html`, writes to `frontend/baseline_screenshots/p1-3d` — all gone | high | delete |
| `DESTRIEUX_FALLBACK` dict in `backend/brain_regions.py` (lines 53-69) | Defined but zero references anywhere in the repo | high | delete the constant |
| `_coerce_prediction_output` 2-tuple branch in `backend/api.py` (lines 214-217) | Only caller is `tribe_service.text_to_predictions`, which unconditionally returns a 3-tuple (`backend/model_service.py` line 246) | high | drop the 2-tuple branch, keep the 3-tuple check |
| `scripts/audit_qa_checklist.txt` | Mentions `app.html`, `frontend/baseline_screenshots/p1-3d/` — references things that no longer exist | medium | update references to the current URL structure |
| `TODAY_CHANGELOG_2026-04-11.md` | Describes a `frontend/index.html` + `frontend/app.html` split that was superseded by `frontend_new/` | low | keep (historical changelog by the user's own convention — "be conservative about deleting specs/changelogs") |
| `IMPLEMENTATION_PLAN_FINAL.md` (frontend tree) | Project structure section shows old `frontend/index.html`, `app.js` layout | low | keep (design/history doc) |
| `narrative.py` discovery fallback → plain-name path | Kept as defensive fallback if a new dimension key lands without a discovery headline | low | keep |
| `runtime.py` `fallback_chain`, `model_service.py` fallback loop | Live runtime fallback (MPS → CPU on load failure) | low | keep |

## 3. Files / directories deleted (high confidence)

- `frontend/` (all files, including `baseline_screenshots/p1-3d/`)
- `frontend 2/` (all files, including `baseline_screenshots/p1-3d/`)
- `tests/test_phase_c_contract.py`
- `tests/test_loading_facts_json.py`
- `scripts/validate_loading_facts.py`
- `scripts/capture_p1_brain_baselines.sh`

## 4. In-file edits (high confidence)

- `backend/brain_regions.py`: drop the unused `DESTRIEUX_FALLBACK` dict (lines 53-69).
- `backend/api.py`: collapse `_coerce_prediction_output` to a single 3-tuple
  path. The 2-tuple fallback never fires, since `text_to_predictions` always
  returns `(preds, segments, timing)`.
- `scripts/audit_qa_checklist.txt`: refresh the URL references so they match
  the real frontend_new routes (`/launch`, `/methodology`, no `app.html`,
  no `frontend/baseline_screenshots/` line).

## 5. Low confidence / deferred

- **`TODAY_CHANGELOG_2026-04-11.md`** — describes the interim
  `index.html` + `app.html` split. It is a dated changelog and the parent
  instructions say to be conservative with design/history docs, so I am
  leaving it in place. Flagged here so the parent can choose to drop it.
- **`IMPLEMENTATION_PLAN_FINAL.md`** — project tree shows the old layout.
  Still useful as design history; rewriting it is a larger doc pass.
- **`/api/diff` sync endpoint (`backend/api.py` line 467)** — the live UI
  only uses the async `start` + `status` flow. The sync endpoint is still
  exercised by `tests/test_api.py`, so it is not strictly legacy; deleting
  it would mean rewriting a good chunk of tests. Left alone.
- **`backend/narrative.py`** `PLAIN_NAMES` path inside `build_headline` —
  currently only reachable if a new dimension is added without a discovery
  headline. Kept as a small defensive fallback.

## 6. Sanity checks run after edits

- `python3 -m py_compile backend/*.py` → OK
- `python3 -m py_compile tests/*.py` → OK
- `grep -r "frontend 2" --include="*.py" --include="*.js" --include="*.html" --include="*.sh" .` → no runtime references
- `grep -r "^from frontend" --include="*.py" .` → no hits
- `grep -rn "frontend/" backend scripts tests` → no runtime references after edits
