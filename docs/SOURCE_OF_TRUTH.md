# BrainDiff — Folders, Repos, and Source of Truth

**Last updated:** 2026-04-28
**Maintainer note:** This is the only doc that says "where is the latest." If you change folders or remotes, update this doc in the same commit.

---

## TL;DR

**The latest, active product lives here:**

```
/Users/ishita/Downloads/Work code/Brain Diff - all in/braindiff_v2/
```

That's where Cursor will run the audio/video implementation plan. The currently-running backend (when up) is launched from this folder. Everything else listed below is either an older snapshot, a reference, or a sibling experiment.

---

## Local folders (under `/Users/ishita/Downloads/Work code/`)

| Folder | Status | Repo it tracks | Branch | Last commit | Role |
|---|---|---|---|---|---|
| **`Brain Diff - all in/braindiff_v2/`** | **ACTIVE — primary working copy** | **`ishita7077/runpod_braindiff_test` only** (`git remote` name: `origin` → that repo) | `cleanup/vibecode-cleanse` tracks **`origin/main`** | `1661a8f` (Turnstile optional + Vercel/Runpod tooling) | Vercel + Runpod stack, audio/video on `/launch`. `braindiff_v2` is **not** a remote on this clone anymore — add it only if you need a second upstream. |
| `Brain Diff v2/` | Older working copy | `ishita7077/braindiff_v2` | `cleanup/vibecode-cleanse` | `c70abbf feat: complete cleanup pass and light-first BrainDiff refresh` | Predecessor to the "all in" copy. Has its own `.venv` from earlier setup. **10 dirty files** — pending changes that were never committed. Source of the bundled `.tools/bin/ffmpeg` we copied to the active copy. |
| `braindiff_claude/` | Reference / former production copy | `ishita7077/braindiff_v1` (404 — repo gone from GitHub) | `main` | `44a5ce3 feat: landing + results + run redesign, real time-series dim graphs, deep scope` | The instance described in the operating primer. Was the previously-running backend before we cut over. Clean working tree. **Origin URL is dead — do not push.** |
| `Brain Diff/` | Documentation snapshot (not git) | — | — | — | Loose `.md` and `.html` files: `BUILDER_LOG.md`, `CURSOR.md`, `a11y_review.md`, `handoff_results.md`, plus standalone `landing.html`, `results.html`, `run.html`. Treat as historical scratch. |
| `braindiff_v1-main/` | Source-of-truth specs (not git) | — | — | — | Original spec set: `DIMENSIONS_SPEC_FINAL.md`, `IMPLEMENTATION_PLAN_FINAL.md`, `NORTH_STAR_FINAL.md`, `RUN_LOCAL.md`, `UX_SPEC_FINAL.md`, plus `BrainDiff_Audit_and_Cursor_Execution_Map.xlsx`. Reference only — code in `backend/`, `atlases/` here is a frozen snapshot from earlier. |

### Disk pressure (informational)

```
Brain Diff - all in   2.1 GB     ← active
Brain Diff v2         1.3 GB     ← older clone
braindiff_claude      2.3 GB     ← reference
Brain Diff            784 MB     ← docs scratch
braindiff_v1-main     6.3 MB     ← specs
─────────────────────────────
total                ~6.5 GB
```

If disk gets tight, the safe-to-delete candidates are `Brain Diff/` (just `.md` + `.html`, none of which are referenced by the build) and `braindiff_v1-main/` (specs only — keep a copy elsewhere first). `Brain Diff v2/` and `braindiff_claude/` should stay until the active copy has been validated end-to-end by Cursor.

---

## GitHub repos

| Repo | Role for this project |
|---|---|
| **`https://github.com/ishita7077/runpod_braindiff_test`** | **Only push target** for the active folder. Local `origin` points here. **`main`** is what Vercel/GitHub Actions should track for deploy. |
| `ishita7077/braindiff_v2` | Separate public repo — **not** wired as a remote in this clone (avoids pushing deploy work to the wrong place). Add with `git remote add upstream-braindiff https://github.com/ishita7077/braindiff_v2.git` only if you need it. |
| `ishita7077/braindiff_v1` | **404 — gone.** Was the remote of `braindiff_claude/`. |

### Git in `Brain Diff - all in/braindiff_v2/` (this clone)

- **`git remote -v`** should show a single **`origin`** → `https://github.com/ishita7077/runpod_braindiff_test.git`.
- Branch **`cleanup/vibecode-cleanse`** tracks **`origin/main`**. Publish work: **`git push origin HEAD:main`** (or `git push` when configured).
- Do **not** point this clone’s `origin` at `braindiff_v2` for the Runpod/Vercel path unless you explicitly want that.

---

## What's currently in the active copy (`Brain Diff - all in/braindiff_v2/`)

### Backend (`backend/`)
- `api.py` — FastAPI app with `/api/diff/start`, `/api/diff/status/{id}`, `/api/preflight`, `/api/ready`, plus static page routes for `/`, `/research`, `/methodology`, `/launch`, `/run.html`, `/results.html`
- `model_service.py` — `TribeService`: wraps TRIBEv2, currently only `text_to_predictions`
- `schemas.py` — `DiffRequest` (text-only today), `JobStartResponse`, `ReportPair`, `ReportRequest`
- `runtime.py`, `neuralset_mps_patch.py` — Apple Silicon dtype patches and device-selection logic

### Frontend (`frontend_new/`)
- `index.html` — landing page (hero, compare demo, Falk 2012 case study, mapped-systems lens)
- `input.html` — `/launch` page (textarea pair + presets). **Songbird easter egg removed during this session.**
- `run.html` — `/run.html?job=…` deep-scope page (4-step status log, brain carousel, "While you wait")
- `results.html` — results page (3D brain w/ B-A/Just B/Just A toggle, trade-off axis, dimension chart)
- `research.html`, `methodology.html` — citation page + 3-stage pipeline

### Other directories
- `tribev2/` — editable install of `facebookresearch/tribev2` at pinned commit `72399081ed`. Patched with `third_party/tribev2_patches/eventstransforms.py`
- `atlases/` — fsaverage5 brain meshes + HCP atlas files for surface projection
- `tests/` — pytest suite. Run with `BRAIN_DIFF_SKIP_STARTUP=1 PYTHONPATH=. .venv/bin/pytest tests/ -q`
- `scripts/` — `setup_local.sh`, `run_api.sh`, `preflight.sh`, plus `e2e_diff_http.py`, `preview_server.py`
- `.tools/bin/ffmpeg` — bundled ffmpeg binary copied from `Brain Diff v2/.tools/`. The only ffmpeg this clone needs (no brew/system install required)
- `.venv/` — Python 3.11 virtual env with `torch==2.6.0`, `whisperx`, `transformers==4.57.6`, `tribev2` editable, etc.
- `cache/` — gitignored. Will hold uploaded audio/video at `cache/uploads/<job_id>/` once the plan is implemented
- `logs/braindiff.log` — server log file

### Docs (`docs/plans/`)
- `2026-04-24-audio-video-input.md` — the full Cursor implementation brief (11 tasks, full code, commit messages). **This is the next thing to execute.**

### `node_modules/`
- Listed in `.gitignore`. `package-lock.json` is committed for the Vercel adapter.

---

## Hugging Face cache (system-wide — not in any folder above)

| Path | Models | Size | Status |
|---|---|---|---|
| `~/.cache/huggingface/hub/` | `meta-llama/Llama-3.2-3B`, `facebook/tribev2`, `facebook/w2v-bert-2.0`, `Systran/faster-whisper-*` | ~10 GB | **shared** by every clone. Do not duplicate. |
| `~/.cache/huggingface/token` | HF token (used for gated Llama access) | 37 B | shared |

**Not yet cached:** `facebook/vjepa2-vitg-fpc64-256` (the video feature extractor). The audio/video plan adds a `POST /api/warmup/video-extractor` endpoint that pulls it on demand; first call will be slow.

---

## Running the active copy

When the backend is **down** (verify with `lsof -iTCP:8000 -sTCP:LISTEN`) and you want it back up:

```bash
cd "/Users/ishita/Downloads/Work code/Brain Diff - all in/braindiff_v2"
export PATH="$(pwd)/.tools/bin:$PATH"
TOKENIZERS_PARALLELISM=false \
  TRIBEV2_NUM_WORKERS=2 \
  BRAIN_DIFF_STARTUP_WARMUP=0 \
  BRAIN_DIFF_MAX_CONCURRENT_JOBS=2 \
  ./scripts/run_api.sh > logs/braindiff.log 2>&1 &
```

Wait for `Application startup complete` in `logs/braindiff.log`, then visit `http://localhost:8000`.

---

## Pre-ship reminders (do NOT forget)

1. **Upload cleanup.** Once audio/video uploads are live, `cache/uploads/<job_id>/` accumulates forever. Add a reaper before public launch.
2. **Verify 30s truncation branch.** Submit a >30s clip and confirm the result page renders the truncation warning correctly.
3. **`origin` remote.** Keep it on **`runpod_braindiff_test`** for this deploy path unless you deliberately add a second remote.

---

## Quick orientation for a future session

If a future Claude or Cursor agent reads this doc with no context, the order of operations is:

1. **Skim** this file (`docs/SOURCE_OF_TRUTH.md`) — understand which folder is active.
2. **Skim** `CLAUDE.md` (the operating primer) — understand the design taste, killed features, env vars.
3. **Skim** `docs/plans/2026-04-24-audio-video-input.md` — the next big change.
4. **Run** `git status && git log --oneline -10` to see where the working tree actually is.
5. **Ask the user** before restarting the backend or pushing anywhere.
