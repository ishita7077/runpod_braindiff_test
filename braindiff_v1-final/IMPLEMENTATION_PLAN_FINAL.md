# Brain Diff — Implementation Plan (FINAL)

Reference: NORTH_STAR_FINAL.md, DIMENSIONS_SPEC_FINAL.md, UX_SPEC_FINAL.md

---

## AGENT BUILD CONTRACT — READ THIS FIRST

If you are GPT, Cursor, Claude Code, Devin, or any other coding agent building this project, these rules are non-optional. Violating any of them means the build is broken even if the code runs.

### Rule 1: Hard-fail on atlas
- Production mode starts ONLY with HCP MMP1.0 loaded and verified
- Destrieux is allowed ONLY in local sandbox/dev with a visible warning
- If HCP labels don't match expected names → abort startup, print all labels, stop
- NEVER silently fall back to a different atlas

### Rule 2: Pin everything
- Pin exact `facebook/tribev2` model revision (commit hash)
- Pin exact TRIBE repo commit
- Pin Python version (3.10.x)
- Pin CUDA version
- Pin ALL Python dependencies with exact versions in requirements.txt
- Store atlas artifact checksum (SHA256)
- Store `atlas_labels.txt` in the repo as ground truth
- On every startup, verify checksums match

### Rule 3: Do not invent mappings
- Use ONLY area names listed in DIMENSIONS_SPEC_FINAL.md
- If a name is missing from the atlas → LOG IT AND FAIL
- NEVER silently substitute a nearby parcel
- NEVER guess that "Area_44" is the same as "44" without confirming
- If you need to try multiple name formats, try ALL of them, log which one worked, and FAIL if none match

### Rule 4: Install exactly like this
```bash
# Step 1: Clone official TRIBE repo
git clone https://github.com/facebookresearch/tribev2.git
cd tribev2

# Step 2: Install with official editable path
pip install -e .

# Step 3: Authenticate with HuggingFace
huggingface-cli login
# Paste your token. Must have access to meta-llama/Llama-3.2-3B (gated model)

# Step 4: Run official smoke test FIRST
python -m tribev2.grids.test_run
# If this fails, DO NOT proceed. Fix the environment first.

# Step 5: ONLY THEN install Brain Diff dependencies
pip install nilearn fastapi uvicorn
```
Do NOT skip step 4. Do NOT invent your own install path. Do NOT use `pip install tribev2` (it's not on PyPI).

### Rule 5: Use signed contrast as primary
- Public delta bars use signed ROI contrast: `mean(preds_B[mask]) - mean(preds_A[mask])`
- Heatmap uses the same signed basis: `preds_B.mean(axis=0) - preds_A.mean(axis=0)`
- `np.abs()` may ONLY be used for a secondary "magnitude" field, never as primary
- If you see yourself writing `np.abs()` for the main score, STOP and re-read this rule

### Rule 6: Save reproducibility artifacts on every startup
On server start, write `startup_manifest.json`:
```json
{
  "timestamp": "2026-04-06T12:00:00Z",
  "tribev2_revision": "abc123...",
  "atlas": "HCP_MMP1.0",
  "atlas_checksum": "sha256:...",
  "atlas_labels_hash": "sha256:...",
  "python_version": "3.10.14",
  "cuda_version": "11.8",
  "torch_version": "2.1.0",
  "dependency_lock_hash": "sha256:...",
  "text_encoder_auth": true,
  "gpu_name": "NVIDIA A100",
  "gpu_memory_gb": 40
}
```

### Rule 7: Hard QC gates
- Empty text → 400 error, do not process
- Text > 5000 chars → 400 error
- Text < 10 chars → 200 but include `"warning": "Very short text may produce unreliable results"`
- Large length mismatch (one text 10x longer than other) → include `"warning": "Large length difference may affect comparison"`
- If any ROI has 0 vertices after mask building → abort startup, log which ROI failed
- If any dimension has `magnitude < 0.005` → mark confidence `"low"`; frontend must render this as dashed bar + `~` delta

### Rule 8A: Loading status must be real-time and backend-driven
- Loading UI updates must come from real backend progress events, not timers
- Required step order:
  1. `converting_text_to_speech`
  2. `predicting_version_a`
  3. `predicting_version_b`
  4. `computing_brain_contrast`
  5. `done`
- On failure, emit `error` with machine-readable `code` and human-readable `message`
- If processing > 15000ms, emit `slow_processing` so UI can show: "Still processing - longer texts take more time"

### Rule 8: Canonical output schema
Every `/api/diff` response MUST match this exact structure:
```json
{
  "diff": {
    "personal_resonance": {
      "score_a": 0.0312,
      "score_b": 0.0498,
      "delta": 0.0186,
      "direction": "B_higher",
      "magnitude": 0.0186,
      "confidence": "high"
    },
    "social_thinking": { "..." : "same structure" },
    "brain_effort": { "..." : "same structure" },
    "language_depth": { "..." : "same structure" },
    "gut_reaction": { "..." : "same structure" }
  },
  "vertex_delta": [20484 signed float values],
  "warnings": [],
  "meta": {
    "model_revision": "facebook/tribev2@abc123",
    "atlas": "HCP_MMP1.0",
    "method_primary": "signed_roi_contrast",
    "normalization": "within_stimulus_median",
    "text_to_speech": true,
    "text_a_length": 42,
    "text_b_length": 67,
    "text_a_timesteps": 5,
    "text_b_timesteps": 8,
    "processing_time_ms": 3400
  }
}
```
Do NOT add fields. Do NOT remove fields. Do NOT rename fields. The frontend depends on this exact shape.

### Rule 9: Run tests in this exact order
```bash
pytest tests/test_install.py          # Can we import everything?
pytest tests/test_model_smoke.py      # Does TRIBEv2 run on a test sentence?
pytest tests/test_atlas_labels.py     # Do all expected HCP labels exist?
pytest tests/test_masks_nonzero.py    # Do all 5 dimensions have >0 vertices?
pytest tests/test_signed_diff.py      # Is diff symmetric? (A-B = -(B-A))
pytest tests/test_heatmap_basis.py    # Is heatmap using same signed math as bars?
pytest tests/test_sanity_pairs.py     # Do known pairs produce correct directions?
pytest tests/test_api.py              # Does the API return correct JSON shape?
```
If ANY test fails, do NOT proceed to the next one. Fix the failing test first.

### Rule 10: Never silently continue
- No silent Destrieux fallback
- No silent parcel drop (if a parcel name doesn't match, FAIL LOUDLY)
- No silent switch from signed to abs
- No silent CPU downgrade (if GPU is unavailable, abort with clear message)
- No silent swallowing of exceptions (every except block MUST log the full traceback)
- No `pass` in except blocks. Ever.

---

## GPT / CURSOR COMMON MISTAKES — READ THIS IF YOU ARE AN AI AGENT

These are mistakes that GPT-4, Cursor, and other coding agents make repeatedly when building Python ML projects. Each one has been observed in real builds.

### Mistake 1: Inventing package names
```python
# WRONG — tribev2 is not on PyPI
pip install tribev2

# RIGHT — clone and install from source
git clone https://github.com/facebookresearch/tribev2.git
pip install -e ./tribev2
```
If you don't know the install method, READ THE REPO README. Do not guess.

### Mistake 2: Assuming import paths
```python
# WRONG — guessing the import
from tribev2.model import TribeModel

# RIGHT — use what the README says
from tribev2 import TribeModel
```
If the import fails, check the repo's `__init__.py` and `demo_utils.py` for the actual export.

### Mistake 3: Not authenticating for gated models
TRIBEv2 uses LLaMA 3.2-3B as its text encoder. This is a GATED model on HuggingFace. You MUST:
1. Have a HuggingFace account
2. Request access to `meta-llama/Llama-3.2-3B`
3. Run `huggingface-cli login` with a token that has read access
4. If you skip this, the model will fail at inference time with an opaque 401 error

### Mistake 4: Swallowing errors in try/except
```python
# WRONG — silent failure
try:
    preds = model.predict(events=df)
except:
    pass

# WRONG — catching too broad, no logging
try:
    preds = model.predict(events=df)
except Exception:
    preds = None

# RIGHT — specific exception, full logging, re-raise if fatal
try:
    preds, segments = model.predict(events=df)
except RuntimeError as e:
    logger.error(f"TRIBEv2 inference failed: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail=f"Model inference failed: {str(e)}")
```

### Mistake 5: Not checking tensor shapes
```python
# WRONG — assuming shape is correct
scores = preds[:, mask].mean()

# RIGHT — verify first
assert preds.shape[1] == 20484, f"Expected 20484 vertices, got {preds.shape[1]}"
assert mask.shape[0] == 20484, f"Mask shape mismatch: {mask.shape[0]}"
assert mask.sum() > 0, f"Empty mask for dimension — 0 vertices matched"
regional = preds[:, mask]
logger.info(f"Regional extraction: preds {preds.shape}, mask {mask.sum()} vertices, regional {regional.shape}")
scores = regional.mean()
```

### Mistake 6: Hardcoding atlas label indices
```python
# WRONG — hardcoding index numbers
mPFC_mask = (left_map == 15) | (left_map == 23)

# RIGHT — look up by name
area_name = "10r"
if area_name in clean_labels:
    idx = clean_labels.index(area_name)
    mPFC_mask |= (left_map == idx)
else:
    logger.error(f"Area '{area_name}' not found in atlas labels!")
    raise ValueError(f"Missing atlas area: {area_name}")
```
Label indices are NOT stable across atlas versions or loading methods. Always look up by name.

### Mistake 7: Forgetting the hemodynamic lag
TRIBEv2 predictions are offset by 5 seconds to account for the delay between neural activity and blood flow change. This means:
- For a short text (< 5 seconds of speech), the first few timesteps may be near-zero
- Do NOT panic if the first timesteps are low — check timesteps 5+
- Log the number of timesteps and flag if total timesteps < 6

```python
if preds.shape[0] < 6:
    logger.warning(f"Only {preds.shape[0]} timesteps — text may be too short for reliable prediction")
    warnings.append("Very short text may produce unreliable results due to hemodynamic lag")
```

### Mistake 8: Not converting TRIBEv2 output from torch to numpy
```python
# TRIBEv2 may return torch tensors
preds, segments = model.predict(events=df)

# ALWAYS convert
import numpy as np
if hasattr(preds, 'numpy'):
    preds = preds.detach().cpu().numpy()
elif hasattr(preds, 'values'):
    preds = preds.values
preds = np.array(preds, dtype=np.float32)
logger.info(f"Predictions converted to numpy: shape={preds.shape}, dtype={preds.dtype}")
```

### Mistake 9: Not handling the text-to-speech step
TRIBEv2 converts text to speech internally using `get_events_dataframe(text_path=...)`. This requires:
- A text FILE on disk (not a string in memory)
- The text-to-speech engine to be installed (espeak, ffmpeg, or similar)
- If TTS fails, the error may be cryptic — log the full traceback

```python
import tempfile
import os

def text_to_predictions(model, text_content: str):
    """Write text to temp file, run TRIBEv2, clean up."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write(text_content)
        temp_path = f.name
    
    try:
        logger.info(f"Processing text ({len(text_content)} chars) via temp file: {temp_path}")
        df = model.get_events_dataframe(text_path=temp_path)
        logger.info(f"Events dataframe created: {len(df)} events")
        
        preds, segments = model.predict(events=df)
        logger.info(f"Prediction complete: shape={preds.shape}")
        
        return preds, segments
    except Exception as e:
        logger.error(f"Text processing failed: {e}", exc_info=True)
        raise
    finally:
        os.unlink(temp_path)
        logger.debug(f"Temp file cleaned up: {temp_path}")
```

### Mistake 10: Building the frontend before the backend works
Do NOT start Phase 4 (frontend) until ALL of these pass:
- `test_model_smoke.py` ✅
- `test_atlas_labels.py` ✅
- `test_masks_nonzero.py` ✅
- `test_sanity_pairs.py` ✅
- `test_api.py` ✅


---

## ERROR LOGGING STANDARD

Every Python file in this project MUST follow this pattern. The goal is "single-hop debugging": one error log entry should tell us what failed, where, why, and what input shape/state caused it.

```python
import logging

# Module-level logger — name matches the file
logger = logging.getLogger("braindiff.MODULE_NAME")

# At the start of every function that can fail:
logger.info("FUNCTION_NAME:start", extra={
    "request_id": request_id,
    "stage": "FUNCTION_NAME",
    "text_a_len": len(text_a) if text_a is not None else None,
    "text_b_len": len(text_b) if text_b is not None else None,
})

# After every successful operation:
logger.info("FUNCTION_NAME:ok", extra={
    "request_id": request_id,
    "duration_ms": duration_ms,
    "pred_shape": tuple(preds.shape) if preds is not None else None,
    "mask_vertices": int(mask.sum()) if mask is not None else None,
})

# For recoverable issues:
logger.warning(f"FUNCTION_NAME: WHAT_WENT_WRONG — WHAT_WE_DID_INSTEAD")

# For failures:
logger.error("FUNCTION_NAME:failed", exc_info=True, extra={
    "request_id": request_id,
    "error_type": type(e).__name__,
    "error_message": str(e),
    "stage": "FUNCTION_NAME",
    "duration_ms": duration_ms,
    "text_a_len": len(text_a) if text_a is not None else None,
    "text_b_len": len(text_b) if text_b is not None else None,
    "pred_shape": tuple(preds.shape) if preds is not None else None,
})

# RULES:
# 1. NEVER use print() for logging. Always use logger.
# 2. NEVER log user text content (privacy). Log text LENGTH only.
# 3. ALWAYS include exc_info=True in error logs (gives full traceback).
# 4. ALWAYS log input/output shapes for numpy/torch operations.
# 5. NEVER have an empty except block. NEVER write `except: pass`.
# 6. Every function that touches model/atlas/scoring MUST log start + success + failure.
# 7. Every request gets a request_id. Propagate it across API, model, scoring, heatmap, and narrative logs.
# 8. Add stage-level timings: tts_ms, predict_a_ms, predict_b_ms, score_ms, heatmap_ms, total_ms.
# 9. Write failures to both app log and structured JSONL error log (`logs/errors.jsonl`).
# 10. If returning HTTP 500, include request_id in response so logs are traceable.
# 11. Never swallow retry errors - log each retry attempt and final failure.
```

Configure in `api.py` startup:
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("braindiff.log"),
        logging.StreamHandler(),
    ],
)
```

Also configure a JSON formatter for `logs/errors.jsonl` with one object per failure containing:
- timestamp, request_id, route, stage
- error_type, error_message, traceback
- text lengths, shapes, durations, model revision, atlas checksum
- host metadata (python version, gpu name, process id)

---

## PHASE 0: Environment & Model Setup

### 0.1 — Install environment
```bash
# Create virtual environment
python3.10 -m venv braindiff_env
source braindiff_env/bin/activate

# Clone TRIBEv2
git clone https://github.com/facebookresearch/tribev2.git
cd tribev2
TRIBE_COMMIT=$(git rev-parse HEAD)
echo "TRIBE commit: $TRIBE_COMMIT"

# Install TRIBEv2
pip install -e .

# Install Brain Diff deps
pip install nilearn fastapi uvicorn

# Freeze all versions
pip freeze > requirements_frozen.txt

# Authenticate HuggingFace
huggingface-cli login
```

**Error check:** If `pip install -e .` fails, read the error. Common causes:
- Missing CUDA → install CUDA toolkit
- Missing torch → install torch first with correct CUDA version
- Missing system deps → check tribev2 README for system requirements

### 0.2 — Run official smoke test
```bash
python -m tribev2.grids.test_run
```
If this fails, the environment is broken. Fix it before touching Brain Diff code.

### 0.3 — Load model and run our smoke test

Create `tests/test_model_smoke.py`:
```python
import logging
import numpy as np

logger = logging.getLogger("braindiff.test_model_smoke")

def test_model_loads_and_predicts():
    from tribev2 import TribeModel
    
    logger.info("Loading TRIBEv2 model...")
    model = TribeModel.from_pretrained("facebook/tribev2", cache_folder="./cache")
    logger.info("Model loaded successfully")
    
    # Write test text
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("The quick brown fox jumps over the lazy dog.")
        temp_path = f.name
    
    try:
        df = model.get_events_dataframe(text_path=temp_path)
        logger.info(f"Events dataframe: {len(df)} events, columns: {list(df.columns)}")
        
        preds, segments = model.predict(events=df)
        
        # Convert to numpy if needed
        if hasattr(preds, 'numpy'):
            preds = preds.detach().cpu().numpy()
        preds = np.array(preds, dtype=np.float32)
        
        logger.info(f"Predictions shape: {preds.shape}")
        logger.info(f"Min: {preds.min():.6f}, Max: {preds.max():.6f}")
        logger.info(f"Negative values exist: {(preds < 0).any()}")
        logger.info(f"Timesteps: {preds.shape[0]}")
        
        assert preds.shape[1] == 20484, f"Wrong vertex count: {preds.shape[1]}"
        assert preds.shape[0] > 0, "Zero timesteps"
        
        logger.info("SMOKE TEST PASSED")
        
    finally:
        os.unlink(temp_path)
```

### 0.4 — Load and verify HCP MMP1.0 atlas

Create `tests/test_atlas_labels.py`:
```python
import logging
import numpy as np

logger = logging.getLogger("braindiff.test_atlas_labels")

# ALL area names we need, organized by dimension
REQUIRED_AREAS = {
    "personal_resonance": {
        "left": ["10r", "10v", "9m", "10d", "32", "25"],
        "right": ["10r", "10v", "9m", "10d", "32", "25"],
    },
    "social_thinking": {
        "right": ["PGi", "PGs", "TPOJ1", "TPOJ2", "TPOJ3"],
    },
    "brain_effort": {
        "left": ["46", "p9-46v", "a9-46v", "8C", "8Av"],
    },
    "language_depth": {
        "left": ["44", "45", "PSL", "STV", "STSdp", "STSvp"],
    },
    "gut_reaction": {
        "left": ["AVI", "AAIC", "MI"],
        "right": ["AVI", "AAIC", "MI"],
    },
}


def test_atlas_loads_and_contains_all_areas():
    """
    Load HCP MMP1.0 atlas and verify every required area name exists.
    
    THIS IS THE MOST IMPORTANT TEST IN THE PROJECT.
    If this fails, the dimension scores are meaningless.
    """
    
    # STEP 1: Load the atlas
    # Try multiple loading strategies — HCP MMP1.0 may be available via:
    # a) TRIBEv2's own utils (check tribev2/utils_fmri.py)
    # b) FreeSurfer annotation files downloaded separately
    # c) Nilearn (may not have HCP MMP1.0 natively)
    
    # STRATEGY A: Check if TRIBEv2 ships with it
    try:
        # Look in the tribev2 codebase for atlas loading
        # This is where you need to actually inspect the repo
        import tribev2.utils_fmri as fmri_utils
        logger.info(f"tribev2.utils_fmri available. Functions: {dir(fmri_utils)}")
        # Look for functions like load_atlas, get_parcellation, etc.
    except ImportError:
        logger.warning("tribev2.utils_fmri not importable")
    
    # STRATEGY B: Load from downloaded annotation files
    # HCP MMP1.0 on fsaverage5: https://figshare.com/articles/HCP-MMP1_0_projected_on_fsaverage/3498446
    # Download lh.HCP-MMP1.annot and rh.HCP-MMP1.annot
    # Load with nibabel:
    try:
        import nibabel as nib
        # These files need to be downloaded and placed in a known location
        lh_annot = nib.freesurfer.read_annot('atlases/lh.HCP-MMP1.annot')
        rh_annot = nib.freesurfer.read_annot('atlases/rh.HCP-MMP1.annot')
        labels_lh, ctab_lh, names_lh = lh_annot
        labels_rh, ctab_rh, names_rh = rh_annot
        
        clean_names_lh = [n.decode() if isinstance(n, bytes) else str(n) for n in names_lh]
        clean_names_rh = [n.decode() if isinstance(n, bytes) else str(n) for n in names_rh]
        
        logger.info(f"HCP MMP1.0 loaded. Left: {len(clean_names_lh)} areas. Right: {len(clean_names_rh)} areas.")
        
        # PRINT ALL LABELS — this is ground truth
        with open("atlas_labels.txt", "w") as f:
            f.write("LEFT HEMISPHERE:\n")
            for i, name in enumerate(clean_names_lh):
                f.write(f"  Index {i}: {name}\n")
            f.write("\nRIGHT HEMISPHERE:\n")
            for i, name in enumerate(clean_names_rh):
                f.write(f"  Index {i}: {name}\n")
        
        logger.info("All labels written to atlas_labels.txt")
        
    except FileNotFoundError:
        logger.error("HCP MMP1.0 annotation files not found in atlases/ directory")
        logger.error("Download from: https://figshare.com/articles/HCP-MMP1_0_projected_on_fsaverage/3498446")
        raise
    except Exception as e:
        logger.error(f"Failed to load HCP MMP1.0: {e}", exc_info=True)
        raise
    
    # STEP 2: Verify every required area exists
    all_found = True
    
    for dim_name, hemispheres in REQUIRED_AREAS.items():
        for hemi, area_names in hemispheres.items():
            label_list = clean_names_lh if hemi == "left" else clean_names_rh
            
            for area in area_names:
                # Try multiple name formats
                candidates = [
                    area,                    # exact: "44"
                    f"L_{area}_ROI" if hemi == "left" else f"R_{area}_ROI",
                    f"L_{area}" if hemi == "left" else f"R_{area}",
                    f"lh.{area}" if hemi == "left" else f"rh.{area}",
                    f"ctx_lh_{area}" if hemi == "left" else f"ctx_rh_{area}",
                ]
                
                found = False
                for candidate in candidates:
                    if candidate in label_list:
                        idx = label_list.index(candidate)
                        n_vertices = int((labels_lh == idx).sum() if hemi == "left" else (labels_rh == idx).sum())
                        logger.info(f"  FOUND: {dim_name} / {hemi} / {area} → matched as '{candidate}' (index {idx}, {n_vertices} vertices)")
                        found = True
                        break
                
                if not found:
                    logger.error(f"  MISSING: {dim_name} / {hemi} / {area} — tried: {candidates}")
                    logger.error(f"  Available labels ({hemi}): {label_list}")
                    all_found = False
    
    assert all_found, "Some required atlas areas are missing. Check logs above."
    logger.info("ALL REQUIRED AREAS FOUND — atlas verification passed")
```

### Phase 0 Exit Criteria
- [ ] `test_model_smoke.py` passes
- [ ] `test_atlas_labels.py` passes — ALL areas found
- [ ] `atlas_labels.txt` saved to repo
- [ ] `requirements_frozen.txt` saved
- [ ] `startup_manifest.json` template created

---

## PHASE 1: Brain Region Mapping & Scoring

### 1.1 — brain_regions.py

Uses the verified atlas labels from Phase 0. Builds boolean masks.

The mask-building code follows the pattern from `test_atlas_labels.py` — try multiple name formats, fail if not found.

**Key requirement:** After building all masks, log a summary:
```
Dimension masks built:
  personal_resonance: 847 vertices (12 areas matched)
  social_thinking: 523 vertices (5 areas matched)
  brain_effort: 612 vertices (5 areas matched)
  language_depth: 934 vertices (6 areas matched)
  gut_reaction: 298 vertices (6 areas matched)
  TOTAL dimension vertices: 3214 / 20484 (15.7%)
```

If any dimension has 0 vertices → abort.

### 1.2 — scorer.py

**SIGNED values. Not abs().** This is the standard in fMRI ROI analysis (Falk et al. 2016, MarsBaR extraction).

```python
def score_predictions(preds: np.ndarray, masks: dict) -> dict:
    """
    preds: (T, 20484) — signed TRIBEv2 output
    masks: from build_vertex_masks()
    """
    # Whole-brain reference for normalization
    whole_brain_median = float(np.median(np.abs(preds)))
    # Note: we use abs() ONLY for the normalization denominator
    # This prevents division by near-zero when the whole brain
    # has balanced positive/negative values
    
    if whole_brain_median < 1e-10:
        logger.error(f"Whole brain median near zero: {whole_brain_median}")
        whole_brain_median = 1e-10
    
    logger.info(f"score_predictions:start preds_shape={preds.shape} dims={list(masks.keys())}")

    scores = {}
    for dim_name, dim_data in masks.items():
        mask = dim_data["mask"]
        
        # SIGNED mean — this is the standard
        regional_signed = preds[:, mask]  # (T, n_vertices)
        raw_signed_mean = float(regional_signed.mean())
        
        normalized_signed_mean = raw_signed_mean / whole_brain_median

        # Per-timestep for timeline
        timeseries = regional_signed.mean(axis=1).tolist()
        
        # Secondary: magnitude (abs mean) for confidence assessment
        raw_abs_mean = float(np.abs(regional_signed).mean())
        
        scores[dim_name] = {
            "raw_signed_mean": raw_signed_mean,
            "normalized_signed_mean": normalized_signed_mean,
            "raw_abs_mean": raw_abs_mean,
            "timeseries": timeseries,
            "vertex_count": int(mask.sum()),
        }
        logger.info(
            f"score_predictions:dim={dim_name} vertices={int(mask.sum())} "
            f"raw_signed={raw_signed_mean:.6f} normalized={normalized_signed_mean:.6f}"
        )
    
    logger.info("score_predictions:ok")
    return scores, whole_brain_median
```

### 1.3 — differ.py

```python
def compute_diff(scores_a, scores_b, median_a, median_b) -> dict:
    diff = {}
    for dim_name in scores_a:
        a = scores_a[dim_name]["normalized_signed_mean"]
        b = scores_b[dim_name]["normalized_signed_mean"]
        
        delta = b - a
        magnitude = abs(delta)
        
        if magnitude < 0.005:
            direction = "neutral"
            confidence = "low"
        elif magnitude < 0.02:
            direction = "B_higher" if delta > 0 else "A_higher"
            confidence = "medium"
        else:
            direction = "B_higher" if delta > 0 else "A_higher"
            confidence = "high"
        
        diff[dim_name] = {
            "score_a": round(a, 6),
            "score_b": round(b, 6),
            "delta": round(delta, 6),
            "direction": direction,
            "magnitude": round(magnitude, 6),
            "confidence": confidence,
        }
    
    return diff
```

### Phase 1 Audit — Sanity Pairs

Create `tests/test_sanity_pairs.py`:

| Text A | Text B | Required direction for B |
|--------|--------|------------------------|
| "Q3 revenue grew 3.2% YoY" | "You nearly died today. Your family waited outside." | personal_resonance: B_higher, gut_reaction: B_higher |
| "Add 500ml of water" | "She didn't know he'd been lying the whole time" | social_thinking: B_higher |
| "Nice weather today" | "The ramifications of quantum chromodynamic perturbation theory..." | brain_effort: B_higher, language_depth: B_higher |
| "Hello" | "The child's face covered in dust stopped the entire room" | gut_reaction: B_higher |

Also test symmetry: `diff(A,B).delta == -diff(B,A).delta` for all dimensions.

**IF ANY PAIR FAILS: STOP. Do not proceed to Phase 2.**

---

## PHASE 2: API Server

FastAPI. Main diff endpoint + real-time status channel. Follows canonical schema from Rule 8.

Key implementation details:
- Model loaded once at startup
- Atlas loaded once at startup
- Masks built once at startup
- startup_manifest.json written at startup
- Each request: write temp files, run TRIBEv2 twice, score (normalized signed), diff, return
- Never log text content. Log text length only.
- Include processing_time_ms in every response
- Expose status events for loading choreography (`/api/diff/status/{job_id}` via SSE or polling)
- Emit exact statuses: converting_text_to_speech, predicting_version_a, predicting_version_b, computing_brain_contrast, done/error
- Include `request_id` and `job_id` in both success and error responses for traceability
- Add API tests for status progression, error status payload, and >15s slow-processing event

---

## PHASE 3: Frontend

Design: Dark. Editorial. Monospace + serif. Brain heatmap is the hero.

### UX contract tests (must pass before launch)
1. Landing: two equal text boxes, `Brain Diff` CTA, clickable examples, methodology link, no marketing sections.
2. Input behavior: autosize to 300px, char counters, empty-box shake on submit, disabled CTA until both non-empty.
3. Loading: real backend-driven status lines with checkmarks in required order, >15s message, retry on error.
4. Reveal choreography: 0.0s hero, 0.3s winner callout, 0.6s delta bars staggered, 1.2s heatmap, 1.5s explanation, 2.0s share pulse.
5. Delta bars: centered zero axis, sorted by magnitude desc, right=Version B higher, left=Version A higher, hover tooltips.
6. Low confidence: dashed bars + `~` on delta + tooltip "Small difference - may not be meaningful."
7. Result hierarchy fixed: headline -> winner strip -> bars -> heatmap -> explanation -> methodology drill-down.
8. Claims guardrail: UI text never claims engagement/virality prediction and every research claim is citable.

### Narrative template (explanatory + cited):
```
"Version B activates [dimension] [X]% more strongly.
Content engaging this region tends to [plain english meaning].
Higher activation here was linked to [real-world outcome] (Falk et al., 2012)."
```

### Methodology page (required):
Full research journey in simple words. Cover:
1. What Brain Diff does (2 sentences)
2. Where brain data comes from (TRIBEv2, 700+ people, text→speech)
3. What the 20,484 numbers are (brain surface points)
4. Why these 5 dimensions (cortical + validated for content)
5. How we compute scores (signed mean, within-stimulus normalization)
6. What this is NOT (not individual brain, not engagement prediction)
7. Key studies in plain language
8. Whose brain is "average" (WEIRD sample caveat)

Write it like a smart friend explaining their research over coffee. Simple words, real science.

### Always-visible footer on every result:
> "Predictions for the population-average brain (TRIBEv2, Meta FAIR). Text processed as speech. Individual responses vary."

### Share image includes:
- 1200x675 PNG output
- Both texts (truncated to ~60 chars with "...")
- Hero headline centered
- All 5 delta bars (delta only, no raw score_a/score_b)
- Brain heatmap (single right-lateral view, right aligned)
- Footer with model/atlas version/date
- "braindiff.xyz" branding

### Share image cannot include:
- Confidence markers (`~`, dashed semantics)
- Full explanation paragraph
- Methodology link

---

## PHASE 4: Edge Cases & Polish

Test: empty, short, long, identical, non-English, emojis, URLs, rapid submissions.
Identical texts must produce delta ≈ 0 for all dimensions.
Share image must look clean on Twitter/LinkedIn.

---

## FILE STRUCTURE

```
braindiff/
├── NORTH_STAR_FINAL.md
├── DIMENSIONS_SPEC_FINAL.md
├── UX_SPEC_FINAL.md
├── IMPLEMENTATION_PLAN_FINAL.md      # This file
│
├── atlases/
│   ├── lh.HCP-MMP1.annot            # Downloaded from figshare
│   ├── rh.HCP-MMP1.annot
│   └── atlas_labels.txt              # Ground truth, generated and committed
│
├── backend/
│   ├── api.py
│   ├── brain_regions.py
│   ├── scorer.py
│   ├── differ.py
│   ├── narrative.py
│   ├── heatmap.py
│   ├── startup_manifest.json         # Generated at startup
│   └── requirements_frozen.txt       # Exact versions
│
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── methodology.html              # Full research journey page
│
├── tests/                            # Run in this order
│   ├── test_install.py
│   ├── test_model_smoke.py
│   ├── test_atlas_labels.py
│   ├── test_masks_nonzero.py
│   ├── test_signed_diff.py
│   ├── test_heatmap_basis.py
│   ├── test_sanity_pairs.py
│   └── test_api.py
│
└── scripts/
    ├── setup_env.sh
    ├── download_atlas.sh             # Downloads HCP MMP1.0 from figshare
    ├── print_atlas_labels.py
    └── deploy.sh
```
