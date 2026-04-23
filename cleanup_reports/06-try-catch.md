# Agent 6 — Try/except and defensive-code audit

## Methodology
```
rg "try:|except\s+\w*" -g "*.py"
```
Walked every try/except site (30 in backend, a few in tests/scripts) and
classified each as KEEP or REMOVE/SIMPLIFY. KEEP requires one of:
- guards an optional third-party import
- catches & narrows an error into a domain error (e.g. `RuntimeError("HF_AUTH_REQUIRED: ...")`)
- converts worker/job failure into an error payload for HTTP or status store
- legit best-effort cache read/write
- graceful degradation of a missing resource

## Inventory & verdict

### Backend

| Location | Purpose | Verdict |
|---|---|---|
| `api.py:137` startup warmup | optional warmup; failure must not crash boot | KEEP |
| `api.py:407` `_run_diff_job` | translates pipeline failure into job error payload | KEEP (this is the error-categorization boundary) |
| `api.py:567` `/api/dimension-masks` | converts atlas-load failure into HTTP 503 | KEEP |
| `runtime.py:72` `import torch` | torch is optional at detection time | KEEP |
| `atlas_peaks.py:34` | atlas files may be missing in non-prod envs | KEEP |
| `startup_manifest.py:49` torch metadata | metadata is decorative, falls back to defaults | KEEP |
| `preflight.py:14` imageio_ffmpeg | optional fallback path | KEEP |
| `preflight.py:26` huggingface_hub | optional | KEEP |
| `preflight.py:30` scan_cache_dir | best-effort pre-check | KEEP |
| `preflight.py:54` accelerate import | optional | KEEP |
| `neuralset_mps_patch.py:42` | patch is conditional on deps | KEEP |
| `model_service.py:11` psutil import | optional | KEEP |
| `model_service.py:47` psutil virtual_memory **inside** `if psutil is not None` guard | redundant defense — if psutil was importable, `virtual_memory()` does not fail on supported platforms | **REMOVE** |
| `model_service.py:66` nested `raise ImportError` caught by its own `except` | Bizarre control-flow — raises a specific error in order to fall through. Collapsed to a ternary. | **SIMPLIFY** |
| `model_service.py:108` tribev2 primary/fallback import | the demo_utils fallback is used by test smoke path | KEEP |
| `model_service.py:149` profile attempt loop | retries across `fallback_chain` devices | KEEP |
| `model_service.py:181` langdetect import | optional patch-point | KEEP |
| `model_service.py:200` imageio_ffmpeg on PATH | optional | KEEP |
| `model_service.py:215` symlink with narrow `FileExistsError`/`OSError` | narrow exceptions, fallback to direct path | KEEP |
| `model_service.py:247` prediction failure → domain errors | maps low-level errors to UX-meaningful codes (`HF_AUTH_REQUIRED`, `WHISPERX_FAILED`, `FFMPEG_REQUIRED`, `UVX_REQUIRED`, `LLAMA_LOAD_FAILED`) | KEEP (core product UX) |
| `heatmap.py:86` `ax.set_facecolor(_bg)` wrapped in bare-Exception pass | silent swallow; matplotlib 3.9.2 always supports `set_facecolor` on 3D axes | **REMOVE** |
| `brain_mesh.py:41` cache read | legit best-effort cache | KEEP |
| `brain_mesh.py:64` cache write | legit best-effort cache | KEEP |

### Tests

`tests/test_model_smoke.py` uses try/except for:
- Primary/fallback `TribeModel` import (skips test when unavailable)
- Text-path failure falls back to audio-only

These are legitimate test-environment handling. **KEEP**.

### Scripts
`scripts/e2e_diff_http.py` — 2 try blocks for HTTP polling loop. Legitimate. **KEEP**.
`third_party/tribev2_patches/eventstransforms.py` — third-party patch, out of scope.

## Implemented changes

### 1. `backend/model_service.py:44-54` — collapse defensive `psutil.virtual_memory()` try/except
Before:
```python
if profile.device != "mps":
    return "cpu"
total_ram = 0
try:
    if psutil is not None:
        total_ram = int(psutil.virtual_memory().total)
except Exception:
    total_ram = 0
if total_ram >= 16 * _GIB:
    return "mps_split"
return "cpu"
```
After:
```python
if profile.device != "mps":
    return "cpu"
total_ram = int(psutil.virtual_memory().total) if psutil is not None else 0
if total_ram >= 16 * _GIB:
    return "mps_split"
return "cpu"
```
Rationale: the import of psutil is already guarded at module top. On platforms where psutil is importable, `virtual_memory()` does not raise. The inner try was dead defense.

### 2. `backend/model_service.py:65-73` — remove the `raise ImportError` / `except Exception` ping-pong
Before:
```python
if "BRAIN_DIFF_MPS_TEXT_MAX_MEMORY" not in os.environ:
    try:
        if psutil is None:
            raise ImportError("psutil not available")
        total_ram = psutil.virtual_memory().total
    except Exception:
        total_ram = 0
    cap = "3500MiB" if total_ram >= 16 * _GIB else "2500MiB"
    os.environ["BRAIN_DIFF_MPS_TEXT_MAX_MEMORY"] = cap
```
After:
```python
if "BRAIN_DIFF_MPS_TEXT_MAX_MEMORY" not in os.environ:
    total_ram = psutil.virtual_memory().total if psutil is not None else 0
    cap = "3500MiB" if total_ram >= 16 * _GIB else "2500MiB"
    os.environ["BRAIN_DIFF_MPS_TEXT_MAX_MEMORY"] = cap
```

### 3. `backend/heatmap.py:86-89` — remove silent-swallow around `ax.set_facecolor(_bg)`
Before:
```python
try:
    ax.set_facecolor(_bg)
except Exception:
    pass
```
After:
```python
ax.set_facecolor(_bg)
```
If this ever raises, we want to know. `matplotlib==3.9.2` (pinned) supports it.

## Deferred / not implemented

None at medium confidence. Every remaining try/except has a clear defensive role (optional deps, graceful degradation, error categorization, or job/HTTP boundaries).

## Sanity check
```
$ python3 -m py_compile backend/*.py tests/*.py scripts/*.py
OK
```

No HTTP shape change. No behavioural change on happy path; only removed impossible-to-hit error branches and collapsed a control-flow-via-exception pattern.
