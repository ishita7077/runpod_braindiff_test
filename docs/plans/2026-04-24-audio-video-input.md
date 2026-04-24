# Audio + Video Input Support — Cursor Implementation Brief

**Paste this whole document as a Cursor prompt. It is self-contained.**

---

## 1. What you are building

BrainDiff currently compares two **text** stimuli by running them through a text→speech→TRIBEv2 pipeline. Users want to compare **audio** and **video** directly. TRIBEv2 already supports all three modalities natively — the work is wiring the backend and frontend for file uploads and modality-aware routing.

## 2. Ground rules (read before touching code)

These come from the project's operating primer. Follow them strictly:

- **Do not upgrade torch.** Stay on `torch==2.6.0`, `torchvision==0.21.0`, `torchaudio==2.6.0`. `tribev2` requires `torch<2.7`.
- **Default to no comments.** Only add a comment when the *why* is non-obvious. Do not write docstrings that restate function signatures.
- **No scope creep.** Do the tasks in this brief. Do not refactor adjacent code, do not "improve" UI you did not touch, do not add abstractions for hypothetical future needs.
- **Backend restart kills in-flight jobs.** The job store is in-memory. Before restarting the running server during testing, verify with the user that nothing is in-flight. After code changes, a restart is required — stop the old process first (`lsof -iTCP:8000 -sTCP:LISTEN -t | xargs -r kill`).
- **Frequent commits.** Commit after each numbered task below, with the message shown at the end of that task.
- **TDD where it pays.** Tasks 1, 2, 4 below are test-first (pure logic). Tasks 3, 5, 6 are integration points where writing a test first would be more pain than value; verify manually with curl + a browser. Tasks 7, 8 are frontend; verify visually in the browser.

## 3. Project layout (absolute paths — note the spaces)

```
/Users/ishita/Downloads/Work code/Brain Diff - all in/braindiff_v2
├── backend/
│   ├── api.py                 (FastAPI app, diff endpoints, preflight)
│   ├── model_service.py       (TribeService: wraps TRIBEv2 model)
│   ├── schemas.py             (Pydantic: DiffRequest, JobStartResponse, ...)
│   └── duration_utils.py      (NEW — you will create this)
├── frontend_new/
│   ├── input.html             (the /launch page)
│   └── run.html               (the /run.html deep-scope page)
├── tribev2/                   (editable install of facebookresearch/tribev2)
├── tests/                     (pytest)
├── scripts/
│   └── run_api.sh             (server launcher)
├── cache/
│   └── uploads/               (NEW — multipart uploads land here, per job_id)
└── docs/plans/
    └── 2026-04-24-audio-video-input.md  (this file)
```

**Always quote the path** in shell commands because it has spaces:

```bash
cd "/Users/ishita/Downloads/Work code/Brain Diff - all in/braindiff_v2"
```

## 4. Runtime commands you will use

```bash
# Kill any server on port 8000:
lsof -iTCP:8000 -sTCP:LISTEN -t | xargs -r kill

# Start the server (REQUIRED env vars — don't skip any):
cd "/Users/ishita/Downloads/Work code/Brain Diff - all in/braindiff_v2"
export PATH="$(pwd)/.tools/bin:$PATH"   # so bundled ffmpeg is found
TOKENIZERS_PARALLELISM=false \
  TRIBEV2_NUM_WORKERS=2 \
  BRAIN_DIFF_STARTUP_WARMUP=0 \
  BRAIN_DIFF_MAX_CONCURRENT_JOBS=2 \
  ./scripts/run_api.sh > logs/braindiff.log 2>&1 &

# Wait until up, then:
curl -s http://127.0.0.1:8000/api/ready | python3 -m json.tool

# Run the test suite (required before every commit):
BRAIN_DIFF_SKIP_STARTUP=1 PYTHONPATH=. .venv/bin/pytest tests/ -q
```

## 5. Product rules (these drive the code)

| Rule | Value | Enforced in |
|---|---|---|
| Text length cap | 5000 characters per side | `backend/schemas.py` (already there, don't change) |
| Text similarity tolerance | A and B must differ by at most **20 characters** | `backend/api.py` `_run_diff_job` |
| Audio/video duration limit | **30 seconds** — anything longer is truncated to first 30s server-side | `backend/api.py` (ffmpeg truncation step before prediction) |
| Audio/video similarity tolerance | A and B must differ by at most **5 seconds** (after truncation) | `backend/api.py` `_run_diff_job` |
| Upload file size cap | **100 MB per file** | `backend/api.py` `/api/diff/upload` + frontend client check |
| Supported audio formats | `.wav, .mp3, .flac, .ogg` | backend + frontend accept attribute |
| Supported video formats | `.mp4, .avi, .mkv, .mov, .webm` | backend + frontend accept attribute |
| Mixed modality | Rejected — both stimuli must be the same modality | `/api/diff/upload` |

**Violations return HTTP 400** (user-fixable) with a clear `detail` message. `_run_diff_job` violations surface as an error status on the job, not as 400.

## 6. TRIBEv2 interface reference (what we are calling)

```python
# tribev2/tribev2/demo_utils.py:243
model.get_events_dataframe(
    text_path=None,   # str | None — path to .txt file
    audio_path=None,  # str | None — path to .wav/.mp3/.flac/.ogg
    video_path=None,  # str | None — path to .mp4/.avi/.mkv/.mov/.webm
)
# Exactly one of the three must be provided. Returns a pandas DataFrame.

model.predict(events=<dataframe>)
# Returns (predictions, segments). predictions is 2D (timesteps, 20484).
```

Audio feature extractor: `facebook/w2v-bert-2.0` (already cached in `~/.cache/huggingface/`).
Video feature extractor: `facebook/vjepa2-vitg-fpc64-256` (large download, can be ~6 GB+ depending on cache state).

## 6.1 Production deployment note (critical)

For serverless or autoscaled deployments (Vercel + GPU worker providers), **do not perform heavyweight model downloads inside request/health endpoints**.

- `/api/preflight` must be fast and side-effect free.
- Video model warmup should run in a separate background/admin path (or startup worker), with cached status exposed by preflight.
- First-user requests must never block on multi-GB downloads.

---

# Task 1 — Duration utilities module (test-first)

**Goal:** A tiny module that probes media duration with ffprobe (or ffmpeg fallback), truncates long files to ≤30s, and checks A/B similarity tolerances.

**Files:**
- Create: `backend/duration_utils.py`
- Create: `tests/test_duration_utils.py`

**Step 1.1** — Write the failing tests.

```python
# tests/test_duration_utils.py
import pytest
from backend.duration_utils import (
    probe_duration_seconds,
    ensure_within_max,
    check_media_similarity,
    check_text_similarity,
    DurationMismatch,
    MAX_MEDIA_SECONDS,
    MEDIA_SIMILARITY_SECONDS,
    TEXT_SIMILARITY_CHARS,
)


def test_probe_duration_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        probe_duration_seconds("/nonexistent/file.mp3")


def test_text_similarity_accepts_close_lengths():
    # 100 chars vs 115 chars → within 20
    check_text_similarity("a" * 100, "b" * 115)


def test_text_similarity_rejects_far_lengths():
    with pytest.raises(DurationMismatch) as exc:
        check_text_similarity("a" * 100, "b" * 150)
    assert "20" in str(exc.value) or "characters" in str(exc.value).lower()


def test_media_similarity_accepts_within_5_seconds():
    # 28s vs 30s — within 5s
    check_media_similarity(28.0, 30.0)


def test_media_similarity_rejects_over_5_seconds():
    with pytest.raises(DurationMismatch) as exc:
        check_media_similarity(10.0, 28.0)
    assert "5" in str(exc.value) or "similar" in str(exc.value).lower()


def test_constants_match_product_rules():
    assert MAX_MEDIA_SECONDS == 30
    assert MEDIA_SIMILARITY_SECONDS == 5
    assert TEXT_SIMILARITY_CHARS == 20
```

Also add a test for `ensure_within_max` using a tmp file you write yourself (synthetic wav). Leave that test for later — it needs a fixture; for now the 6 tests above are enough.

Run them, confirm they fail:

```bash
cd "/Users/ishita/Downloads/Work code/Brain Diff - all in/braindiff_v2"
BRAIN_DIFF_SKIP_STARTUP=1 PYTHONPATH=. .venv/bin/pytest tests/test_duration_utils.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.duration_utils'` on all 6.

**Step 1.2** — Implement `backend/duration_utils.py`:

```python
from __future__ import annotations

import json
import os
import subprocess


class DurationMismatch(ValueError):
    """A and B durations/lengths violate the product's similarity rule."""


class DurationProbeError(RuntimeError):
    """Duration could not be read from media content."""


MAX_MEDIA_SECONDS: int = 30
MEDIA_SIMILARITY_SECONDS: int = 5
TEXT_SIMILARITY_CHARS: int = 20


def probe_duration_seconds(path: str) -> float:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                path,
            ],
            stderr=subprocess.STDOUT,
        )
        return float(json.loads(out)["format"]["duration"])
    except (FileNotFoundError, subprocess.CalledProcessError, KeyError, json.JSONDecodeError):
        pass

    try:
        result = subprocess.run(["ffmpeg", "-i", path], capture_output=True, text=True)
    except FileNotFoundError as err:
        raise FileNotFoundError(f"ffmpeg/ffprobe not on PATH (probing {path})") from err
    for line in result.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = hms.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise DurationProbeError(f"Could not read duration from media file: {path}")


def ensure_within_max(path: str, *, max_seconds: int = MAX_MEDIA_SECONDS) -> tuple[str, float, bool]:
    duration = probe_duration_seconds(path)
    if duration <= max_seconds:
        return path, duration, False
    base, ext = os.path.splitext(path)
    trimmed = f"{base}.trim{ext}"
    # First try stream copy for speed; if container/codec boundaries make that unreliable,
    # fall back to a deterministic re-encode path.
    copy_cmd = [
        "ffmpeg", "-y",
        "-ss", "0",
        "-i", path,
        "-t", str(max_seconds),
        "-c", "copy",
        trimmed,
    ]
    try:
        subprocess.check_call(copy_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        recode_cmd = [
            "ffmpeg", "-y",
            "-ss", "0",
            "-i", path,
            "-t", str(max_seconds),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-movflags", "+faststart",
            trimmed,
        ]
        subprocess.check_call(recode_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return trimmed, float(max_seconds), True


def check_media_similarity(
    seconds_a: float,
    seconds_b: float,
    *,
    tolerance: int = MEDIA_SIMILARITY_SECONDS,
) -> None:
    if abs(seconds_a - seconds_b) > tolerance:
        raise DurationMismatch(
            f"Stimuli durations differ by {abs(seconds_a - seconds_b):.1f}s "
            f"({seconds_a:.1f}s vs {seconds_b:.1f}s). "
            f"Both stimuli must be within {tolerance}s of each other."
        )


def check_text_similarity(
    text_a: str,
    text_b: str,
    *,
    tolerance: int = TEXT_SIMILARITY_CHARS,
) -> None:
    if abs(len(text_a) - len(text_b)) > tolerance:
        raise DurationMismatch(
            f"Text lengths differ by {abs(len(text_a) - len(text_b))} characters "
            f"({len(text_a)} vs {len(text_b)}). "
            f"Both stimuli must be within {tolerance} characters of each other."
        )
```

Re-run the tests — all 6 should pass.

**Commit:**

```bash
git add backend/duration_utils.py tests/test_duration_utils.py
git commit -m "feat: add duration + similarity utilities for multimodal inputs"
```

---

# Task 2 — Multimodal `DiffRequest` schema

**Goal:** Extend `DiffRequest` so exactly one modality pair must be provided. Keep the existing `ReportPair` / `ReportRequest` as-is.

**Files:**
- Modify: `backend/schemas.py` (full rewrite)
- Create: `tests/test_schemas.py`

**Step 2.1** — Write the failing tests:

```python
# tests/test_schemas.py
import pytest
from pydantic import ValidationError
from backend.schemas import DiffRequest


def test_text_only_request_still_valid():
    req = DiffRequest(text_a="Hello world.", text_b="Goodbye world.")
    assert req.modality() == "text"


def test_audio_request_uses_audio_paths():
    req = DiffRequest(audio_path_a="/tmp/a.wav", audio_path_b="/tmp/b.wav")
    assert req.modality() == "audio"


def test_video_request_uses_video_paths():
    req = DiffRequest(video_path_a="/tmp/a.mp4", video_path_b="/tmp/b.mp4")
    assert req.modality() == "video"


def test_mixed_modality_rejected():
    with pytest.raises(ValidationError):
        DiffRequest(text_a="Hello.", audio_path_b="/tmp/b.wav")


def test_missing_pair_rejected():
    with pytest.raises(ValidationError):
        DiffRequest(text_a="Hello.")


def test_no_inputs_rejected():
    with pytest.raises(ValidationError):
        DiffRequest()
```

Run them — all fail with current schema.

**Step 2.2** — Replace `backend/schemas.py` entirely:

```python
from pydantic import BaseModel, Field, model_validator


class DiffRequest(BaseModel):
    text_a: str | None = Field(default=None, min_length=1, max_length=5000)
    text_b: str | None = Field(default=None, min_length=1, max_length=5000)
    audio_path_a: str | None = None
    audio_path_b: str | None = None
    video_path_a: str | None = None
    video_path_b: str | None = None

    @model_validator(mode="after")
    def _exactly_one_modality(self):
        pairs = {
            "text": (self.text_a, self.text_b),
            "audio": (self.audio_path_a, self.audio_path_b),
            "video": (self.video_path_a, self.video_path_b),
        }
        complete = [name for name, (a, b) in pairs.items() if a is not None and b is not None]
        if len(complete) != 1:
            raise ValueError(
                "DiffRequest must specify exactly one modality pair: "
                "(text_a + text_b) OR (audio_path_a + audio_path_b) OR (video_path_a + video_path_b). "
                f"Got complete pairs: {complete or 'none'}."
            )
        return self

    def modality(self) -> str:
        if self.text_a is not None and self.text_b is not None:
            return "text"
        if self.audio_path_a is not None and self.audio_path_b is not None:
            return "audio"
        return "video"


class JobStartResponse(BaseModel):
    job_id: str
    request_id: str
    status: str


class ReportPair(BaseModel):
    text_a: str = Field(..., min_length=1, max_length=5000)
    text_b: str = Field(..., min_length=1, max_length=5000)
    label: str = Field(..., min_length=1, max_length=200)


class ReportRequest(BaseModel):
    pairs: list[ReportPair] = Field(..., min_length=1, max_length=20)
```

Run all tests — they should all pass:

```bash
BRAIN_DIFF_SKIP_STARTUP=1 PYTHONPATH=. .venv/bin/pytest tests/ -q
```

**Commit:**

```bash
git add backend/schemas.py tests/test_schemas.py
git commit -m "feat: extend DiffRequest to accept audio/video modalities"
```

---

# Task 3 — `audio_to_predictions` + `video_to_predictions` on TribeService

**Goal:** Two new methods on `TribeService` that call TRIBEv2's native audio/video paths. Structurally mirror `text_to_predictions` (which lives at `backend/model_service.py:216-270`).

**Files:**
- Modify: `backend/model_service.py`

**Step 3.1** — After the closing of `text_to_predictions` (the `finally: os.unlink(temp_path)` at ~line 270), insert:

```python
    def audio_to_predictions(self, audio_path: str):
        return self._media_to_predictions(audio_path, kind="audio")

    def video_to_predictions(self, video_path: str):
        return self._media_to_predictions(video_path, kind="video")

    def _media_to_predictions(self, path: str, kind: str):
        if self.model is None:
            raise RuntimeError("TRIBEv2 model not loaded")
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        kwargs = {"audio_path": path} if kind == "audio" else {"video_path": path}
        t0 = time.perf_counter()
        try:
            events = self.model.get_events_dataframe(**kwargs)
        except Exception as err:
            msg = str(err).lower()
            if "whisperx failed" in msg or "ctranslate2" in msg:
                raise RuntimeError(
                    f"WHISPERX_FAILED: Transcription step in the {kind} pipeline failed. "
                    f"Detail: {err}"
                ) from err
            raise
        events_ms = int((time.perf_counter() - t0) * 1000)
        t1 = time.perf_counter()
        preds, segments = self.model.predict(events=events)
        predict_ms = int((time.perf_counter() - t1) * 1000)
        if hasattr(preds, "detach"):
            preds = preds.detach().cpu().numpy()
        elif hasattr(preds, "values"):
            preds = preds.values
        preds_np = np.array(preds, dtype=np.float32)
        if preds_np.ndim != 2:
            raise ValueError(f"Unexpected predictions shape: {preds_np.shape}")
        return preds_np, segments, {"events_ms": events_ms, "predict_ms": predict_ms}
```

Do not add any comments — the method is short and self-explanatory.

**Commit:**

```bash
git add backend/model_service.py
git commit -m "feat: audio_to_predictions + video_to_predictions on TribeService"
```

---

# Task 4 — `/api/diff/upload` multipart endpoint + 100 MB cap

**Goal:** New endpoint that accepts two files, validates modality match + size, persists them under `cache/uploads/<job_id>/`, and launches a diff job. Returns 202 + `job_id`.

**Files:**
- Modify: `backend/api.py`
- Create: `tests/test_upload_endpoint.py`

**Step 4.1** — Update imports in `backend/api.py`. Find the line (currently near line 12):

```python
from fastapi import FastAPI, HTTPException
```

Change to:

```python
from fastapi import FastAPI, HTTPException, UploadFile
```

Also add, near the other `backend.*` imports at the top of the file:

```python
from backend.duration_utils import DurationMismatch
```

**Step 4.2** — Write the failing tests:

```python
# tests/test_upload_endpoint.py
"""Contract tests for /api/diff/upload. Keep them deterministic and small."""
import io
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    os.environ["BRAIN_DIFF_SKIP_STARTUP"] = "1"
    from backend.api import app
    with TestClient(app) as c:
        yield c


def test_upload_rejects_mixed_modality(client):
    resp = client.post(
        "/api/diff/upload",
        files={
            "file_a": ("a.wav", io.BytesIO(b"\x00" * 16), "audio/wav"),
            "file_b": ("b.mp4", io.BytesIO(b"\x00" * 16), "video/mp4"),
        },
    )
    assert resp.status_code == 400
    assert "same modality" in resp.json()["detail"].lower()


def test_upload_rejects_unsupported_extension(client):
    resp = client.post(
        "/api/diff/upload",
        files={
            "file_a": ("a.xyz", io.BytesIO(b"\x00"), "application/octet-stream"),
            "file_b": ("b.xyz", io.BytesIO(b"\x00"), "application/octet-stream"),
        },
    )
    assert resp.status_code == 400


def test_upload_accepts_two_audio_files_returns_job_id(client):
    resp = client.post(
        "/api/diff/upload",
        files={
            "file_a": ("a.wav", io.BytesIO(b"\x00" * 1024), "audio/wav"),
            "file_b": ("b.wav", io.BytesIO(b"\x00" * 1024), "audio/wav"),
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
```

Over-size is validated in **manual e2e** using a real file, not giant in-memory blobs in unit tests.

Run — 4 failures (endpoint 404).

**Step 4.3** — Add helpers + endpoint to `backend/api.py`. Insert *just before* the existing `@app.post("/api/diff/start", ...)` decorator (currently near line 440):

```python
UPLOAD_ROOT = os.path.join(os.path.dirname(__file__), "..", "cache", "uploads")
AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg"}
VIDEO_EXTS = {".mp4", ".avi", ".mkv", ".mov", ".webm"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _classify_ext(filename: str) -> str | None:
    ext = os.path.splitext(filename)[1].lower()
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    return None


async def _persist_upload(file: UploadFile, dest_dir: str, slot: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower()
    dest = os.path.join(dest_dir, f"{slot}{ext}")
    total = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                out.close()
                os.remove(dest)
                raise HTTPException(
                    status_code=413,
                    detail=f"{file.filename} exceeds 100 MB size cap.",
                )
            out.write(chunk)
    return dest


@app.post("/api/diff/upload", response_model=JobStartResponse, status_code=202)
async def upload_diff(file_a: UploadFile, file_b: UploadFile) -> JSONResponse:
    kind_a = _classify_ext(file_a.filename or "")
    kind_b = _classify_ext(file_b.filename or "")
    if kind_a is None or kind_b is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file extension(s). "
                f"Audio: {sorted(AUDIO_EXTS)}. Video: {sorted(VIDEO_EXTS)}."
            ),
        )
    if kind_a != kind_b:
        raise HTTPException(
            status_code=400,
            detail=f"Both stimuli must be the same modality (got {kind_a} + {kind_b}).",
        )

    job_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    upload_dir = os.path.join(UPLOAD_ROOT, job_id)
    path_a = await _persist_upload(file_a, upload_dir, "a")
    path_b = await _persist_upload(file_b, upload_dir, "b")

    if kind_a == "audio":
        payload = DiffRequest(audio_path_a=path_a, audio_path_b=path_b)
    else:
        payload = DiffRequest(video_path_a=path_a, video_path_b=path_b)

    job_store.create(job_id, request_id)
    asyncio.create_task(_guarded_diff_job(job_id, request_id, payload))
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "request_id": request_id, "status": "queued"},
    )
```

Verify imports referenced here (`os`, `uuid`, `asyncio`, `JSONResponse`, `job_store`, `DiffRequest`, `_guarded_diff_job`) are already imported at the top of `api.py` — they will be, since `/api/diff/start` uses them.

Run tests — all 4 pass.

**Commit:**

```bash
git add backend/api.py tests/test_upload_endpoint.py
git commit -m "feat: /api/diff/upload multipart endpoint with 100 MB size cap"
```

---

# Task 5 — Modality routing in `_run_diff_job` + truncation + similarity checks

**Goal:** The diff job must branch by modality, truncate audio/video to ≤30s, validate similarity (≤20 chars for text, ≤5s for audio/video), emit modality-aware status labels, and route to the correct `*_to_predictions` method.

**Files:**
- Modify: `backend/api.py` — rewrite `_run_diff_job` (currently lines 293-406) and make `_build_diff_result` (line 226) tolerant of `None` text fields.

**Step 5.1** — Update `_error_code_for_exception` (line 100) to map `DurationMismatch` to a user-facing error. Find the function and add this as the first conditional inside it:

```python
    if isinstance(err, DurationMismatch):
        return ("INPUT_REJECTED", str(err))
```

**Step 5.2** — Rewrite `_run_diff_job` (replace lines 293-406 — entire function body, up to but not including the `except Exception as err:` block that handles errors, which remains unchanged):

```python
def _run_diff_job(job_id: str, request_id: str, payload: DiffRequest) -> None:
    started_at = time.perf_counter()
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    modality = payload.modality()
    warnings = (
        _warnings_for_input(payload.text_a, payload.text_b) if modality == "text" else []
    )
    stage_times: dict[str, int] = {}
    route = "/api/diff/start" if modality == "text" else "/api/diff/upload"

    try:
        if modality == "text":
            from backend.duration_utils import check_text_similarity
            check_text_similarity(payload.text_a, payload.text_b)
            job_store.update_status(job_id, "converting_text_to_speech", "Converting text to speech...")
        else:
            from backend.duration_utils import ensure_within_max, check_media_similarity
            if modality == "audio":
                job_store.update_status(job_id, "decoding_audio", "Decoding audio features...")
                path_a, dur_a, trimmed_a = ensure_within_max(payload.audio_path_a)
                path_b, dur_b, trimmed_b = ensure_within_max(payload.audio_path_b)
                payload = DiffRequest(audio_path_a=path_a, audio_path_b=path_b)
            else:
                job_store.update_status(job_id, "decoding_video", "Decoding video + extracting frames...")
                path_a, dur_a, trimmed_a = ensure_within_max(payload.video_path_a)
                path_b, dur_b, trimmed_b = ensure_within_max(payload.video_path_b)
                payload = DiffRequest(video_path_a=path_a, video_path_b=path_b)
            check_media_similarity(dur_a, dur_b)
            if trimmed_a or trimmed_b:
                warnings.append({
                    "code": "stimulus_truncated",
                    "message": "One or both stimuli were longer than 30s and were truncated to the first 30 seconds.",
                })

        # Identical-text short-circuit (text only — two uploaded files will never be byte-identical from a user POV).
        if modality == "text" and payload.text_a.strip() == payload.text_b.strip():
            job_store.update_status(job_id, "predicting_version_a", "Predicting neural response for Version A...")
            job_store.update_status(job_id, "predicting_version_b", "Predicting neural response for Version B...")
            job_store.update_status(job_id, "computing_brain_contrast", "Computing brain contrast...")
            zero_scores = {dim_name: {"normalized_signed_mean": 0.0} for dim_name in masks.keys()}
            diff = compute_diff(zero_scores, zero_scores)
            dimension_rows = enrich_dimension_payload(diff)
            vertex_delta = np.zeros(20484, dtype=np.float32)
            vertex_a = np.zeros(20484, dtype=np.float32)
            vertex_b = np.zeros(20484, dtype=np.float32)
            t_heat = time.perf_counter()
            heatmap = generate_heatmap_artifact(vertex_delta)
            stage_times["heatmap_ms"] = int((time.perf_counter() - t_heat) * 1000)
            processing_time_ms = int((time.perf_counter() - started_at) * 1000)
            result = _build_diff_result(
                payload=payload, request_id=request_id, job_id=job_id, diff=diff,
                dimension_rows=dimension_rows, warnings=warnings, vertex_delta=vertex_delta,
                vertex_a=vertex_a, vertex_b=vertex_b, heatmap=heatmap, stage_times=stage_times,
                processing_time_ms=processing_time_ms, text_a_timesteps=0, text_b_timesteps=0,
                median_a=0.0, median_b=0.0, identical_short_circuit=True,
            )
            job_store.set_result(job_id, result)
            job_store.update_status(job_id, "done", "Done")
            _persist_run(job_id=job_id, request_id=request_id, created_at=created_at, status="done", success=True, payload=payload, stage_times=stage_times, warnings=warnings, text_a_timesteps=0, text_b_timesteps=0, total_ms=processing_time_ms)
            return

        # Stage A
        if modality == "text":
            job_store.update_status(job_id, "transcribing_version_a", "Transcribing Version A through WhisperX (text → audio)...")
            job_store.update_status(job_id, "predicting_version_a", "Running TRIBE v2 forward pass on Version A (text + audio → cortex)...")
            preds_a, _, timing_a = _coerce_prediction_output(tribe_service.text_to_predictions(payload.text_a))
        elif modality == "audio":
            job_store.update_status(job_id, "transcribing_version_a", "Aligning words in Version A audio (WhisperX)...")
            job_store.update_status(job_id, "predicting_version_a", "Running TRIBE v2 forward pass on Version A (audio → cortex)...")
            preds_a, _, timing_a = _coerce_prediction_output(tribe_service.audio_to_predictions(payload.audio_path_a))
        else:
            job_store.update_status(job_id, "transcribing_version_a", "Extracting video frames + audio for Version A...")
            job_store.update_status(job_id, "predicting_version_a", "Running TRIBE v2 forward pass on Version A (video + audio → cortex)...")
            preds_a, _, timing_a = _coerce_prediction_output(tribe_service.video_to_predictions(payload.video_path_a))
        stage_times["events_a_ms"] = timing_a.get("events_ms", 0)
        stage_times["predict_a_ms"] = timing_a.get("predict_ms", 0)

        if (time.perf_counter() - started_at) * 1000 > 15000:
            job_store.update_status(job_id, "slow_processing", "Still processing - longer stimuli take more time")

        # Stage B
        if modality == "text":
            job_store.update_status(job_id, "transcribing_version_b", "Transcribing Version B through WhisperX (text → audio)...")
            job_store.update_status(job_id, "predicting_version_b", "Running TRIBE v2 forward pass on Version B (text + audio → cortex)...")
            preds_b, _, timing_b = _coerce_prediction_output(tribe_service.text_to_predictions(payload.text_b))
        elif modality == "audio":
            job_store.update_status(job_id, "transcribing_version_b", "Aligning words in Version B audio (WhisperX)...")
            job_store.update_status(job_id, "predicting_version_b", "Running TRIBE v2 forward pass on Version B (audio → cortex)...")
            preds_b, _, timing_b = _coerce_prediction_output(tribe_service.audio_to_predictions(payload.audio_path_b))
        else:
            job_store.update_status(job_id, "transcribing_version_b", "Extracting video frames + audio for Version B...")
            job_store.update_status(job_id, "predicting_version_b", "Running TRIBE v2 forward pass on Version B (video + audio → cortex)...")
            preds_b, _, timing_b = _coerce_prediction_output(tribe_service.video_to_predictions(payload.video_path_b))
        stage_times["events_b_ms"] = timing_b.get("events_ms", 0)
        stage_times["predict_b_ms"] = timing_b.get("predict_ms", 0)

        job_store.update_status(job_id, "computing_brain_contrast", "Computing brain contrast...")
        t2 = time.perf_counter()
        scores_a, median_a = score_predictions(preds_a, masks)
        scores_b, median_b = score_predictions(preds_b, masks)
        diff = compute_diff(scores_a, scores_b)
        dimension_rows = enrich_dimension_payload(diff)
        stage_times["score_diff_ms"] = int((time.perf_counter() - t2) * 1000)
        t_heat = time.perf_counter()
        vertex_delta, vertex_a, vertex_b = compute_vertex_delta(preds_a, preds_b)
        heatmap = generate_heatmap_artifact(vertex_delta)
        stage_times["heatmap_ms"] = int((time.perf_counter() - t_heat) * 1000)

        processing_time_ms = int((time.perf_counter() - started_at) * 1000)
        result = _build_diff_result(
            payload=payload, request_id=request_id, job_id=job_id, diff=diff,
            dimension_rows=dimension_rows, warnings=warnings, vertex_delta=vertex_delta,
            vertex_a=vertex_a, vertex_b=vertex_b, heatmap=heatmap, stage_times=stage_times,
            processing_time_ms=processing_time_ms,
            text_a_timesteps=int(preds_a.shape[0]), text_b_timesteps=int(preds_b.shape[0]),
            median_a=median_a, median_b=median_b,
        )
        job_store.set_result(job_id, result)
        job_store.update_status(job_id, "done", "Done")
        _persist_run(job_id=job_id, request_id=request_id, created_at=created_at, status="done", success=True, payload=payload, stage_times=stage_times, warnings=warnings, text_a_timesteps=int(preds_a.shape[0]), text_b_timesteps=int(preds_b.shape[0]), total_ms=processing_time_ms)
        logger.info(
            "diff_job:ok request_id=%s job_id=%s modality=%s total_ms=%s",
            request_id, job_id, modality, processing_time_ms,
        )
```

Leave the existing `except Exception as err:` block after this function unchanged.

**Step 5.3** — Update `_build_diff_result` (line 226) so it handles the audio/video case where `payload.text_a` / `payload.text_b` are `None`. Find all `payload.text_a` / `payload.text_b` references inside the function body and wrap them:

```python
meta["text_a"] = payload.text_a or ""
meta["text_b"] = payload.text_b or ""
meta["text_a_length"] = len(payload.text_a) if payload.text_a else 0
meta["text_b_length"] = len(payload.text_b) if payload.text_b else 0
```

Also add these two lines to `meta` inside `_build_diff_result`:

```python
meta["modality"] = payload.modality()
meta["stimulus_a_path"] = payload.audio_path_a or payload.video_path_a or ""
meta["stimulus_b_path"] = payload.audio_path_b or payload.video_path_b or ""
```

**Step 5.4** — Run the full test suite:

```bash
BRAIN_DIFF_SKIP_STARTUP=1 PYTHONPATH=. .venv/bin/pytest tests/ -q
```

All tests must pass.

**Step 5.5** — Ask the user before restarting the backend. Then restart (kill old, run new per §4 above), wait for `Application startup complete` in `logs/braindiff.log`, then smoke-test the text path:

```bash
curl -s -X POST http://127.0.0.1:8000/api/diff/start \
  -H "Content-Type: application/json" \
  -d '{"text_a":"Hi there.","text_b":"Hi there."}' | python3 -m json.tool
```

Expected 202 + `job_id`. Poll status; identical-text short-circuit should still return `done` within seconds.

**Commit:**

```bash
git add backend/api.py
git commit -m "feat: modality routing in _run_diff_job with 30s truncation + similarity checks"
```

---

# Task 6 — Background warmup for vjepa2 video extractor (preflight remains fast)

**Goal:** Add explicit background warmup for the video extractor. `/api/preflight` should only **report** warmup/cache status and never trigger a multi-GB download inline.

**Files:**
- Modify: `backend/api.py`

**Step 6.1** — Add a warmup status holder + non-blocking background warmup helper:

```python
VIDEO_EXTRACTOR_WARMUP: dict = {
    "state": "idle",   # idle | warming | ready | error
    "repo_id": "facebook/vjepa2-vitg-fpc64-256",
    "local_path": "",
    "error": "",
    "started_at": "",
    "finished_at": "",
}


def _warm_video_extractor_in_background() -> None:
    repo_id = "facebook/vjepa2-vitg-fpc64-256"
    if VIDEO_EXTRACTOR_WARMUP["state"] in {"warming", "ready"}:
        return
    VIDEO_EXTRACTOR_WARMUP["state"] = "warming"
    VIDEO_EXTRACTOR_WARMUP["error"] = ""
    VIDEO_EXTRACTOR_WARMUP["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    try:
        from huggingface_hub import snapshot_download
        local = snapshot_download(
            repo_id=repo_id,
            allow_patterns=["*.json", "*.safetensors", "*.bin"],
        )
        VIDEO_EXTRACTOR_WARMUP["state"] = "ready"
        VIDEO_EXTRACTOR_WARMUP["local_path"] = local
    except Exception as err:
        VIDEO_EXTRACTOR_WARMUP["state"] = "error"
        VIDEO_EXTRACTOR_WARMUP["error"] = str(err)
    finally:
        VIDEO_EXTRACTOR_WARMUP["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
```

**Step 6.2** — Add a warmup endpoint and call it when needed:

```python
@app.post("/api/warmup/video-extractor")
async def warmup_video_extractor() -> JSONResponse:
    if VIDEO_EXTRACTOR_WARMUP["state"] == "warming":
        return JSONResponse(status_code=202, content={"ok": True, "status": VIDEO_EXTRACTOR_WARMUP})
    asyncio.create_task(asyncio.to_thread(_warm_video_extractor_in_background))
    return JSONResponse(status_code=202, content={"ok": True, "status": VIDEO_EXTRACTOR_WARMUP})
```

**Step 6.3** — Inside `/api/preflight`, report status only (no download call):

```python
"video_extractor": {
    "ok": VIDEO_EXTRACTOR_WARMUP["state"] == "ready",
    "state": VIDEO_EXTRACTOR_WARMUP["state"],
    "repo_id": VIDEO_EXTRACTOR_WARMUP["repo_id"],
    "local_path": VIDEO_EXTRACTOR_WARMUP["local_path"],
    "error": VIDEO_EXTRACTOR_WARMUP["error"],
    "started_at": VIDEO_EXTRACTOR_WARMUP["started_at"],
    "finished_at": VIDEO_EXTRACTOR_WARMUP["finished_at"],
},
```

Do **not** add `"video_extractor_missing"` to `blockers` — a missing vjepa2 is not fatal for text users.

**Step 6.4** — Restart server. Verify:

```bash
# Warmup trigger (returns immediately)
curl -s -X POST http://127.0.0.1:8000/api/warmup/video-extractor | python3 -m json.tool

# Poll preflight status
curl -s http://127.0.0.1:8000/api/preflight | python3 -m json.tool | grep -A 3 video_extractor
```

Expected: preflight is always fast and shows `state: warming` → `state: ready`. Warmup may take several minutes depending on network/cache.

**Commit:**

```bash
git add backend/api.py
git commit -m "feat: add background warmup flow for vjepa2 extractor with preflight status reporting"
```

---

# Task 7 — Modality toggle + dropzone on `/launch`

**Goal:** Add a 3-way pill toggle (Text / Audio / Video) above the existing textareas. When Audio or Video is active, hide the textareas and show two file dropzones. Enforce the 100 MB client-side cap. Route submission: text → existing JSON POST to `/api/diff/start`; audio/video → multipart POST to `/api/diff/upload`.

**File:** `frontend_new/input.html`

**Step 7.1** — In the `<style>` block on `input.html`, add (near the other component styles):

```css
.modality-row{
  display:flex;gap:8px;margin:0 0 20px 0;
  padding:4px;background:var(--surface);border-radius:10px;
  border:1px solid var(--line-2);width:fit-content;
}
.modality-pill{
  font-family:'Inter Tight',system-ui,sans-serif;font-size:13px;font-weight:500;
  padding:7px 16px;border-radius:7px;cursor:pointer;
  background:transparent;color:var(--ink-dim);border:0;
  transition:color .15s ease, background .15s ease;
}
.modality-pill:hover{color:var(--ink)}
.modality-pill.is-active{background:var(--accent);color:#fff}

.dropzone-row{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:0 0 28px 0}
.dropzone{
  display:flex;flex-direction:column;justify-content:center;align-items:center;
  min-height:180px;padding:28px;
  background:var(--surface);border:2px dashed var(--line-2);border-radius:14px;
  cursor:pointer;transition:border-color .18s ease, background .18s ease;
  font-family:'Inter Tight',system-ui,sans-serif;
}
.dropzone:hover, .dropzone.is-dragover{border-color:var(--accent);background:var(--panel)}
.dropzone-label{font-size:14px;color:var(--ink-dim);margin-bottom:8px;text-align:center}
.dropzone-filename{font-size:12px;color:var(--ink);font-family:'JetBrains Mono',monospace;text-align:center;word-break:break-all}
```

**Step 7.2** — Find the form's existing two-textarea block in the markup. Immediately *before* it, add the modality toggle:

```html
<div class="modality-row" role="radiogroup" aria-label="Stimulus modality">
  <button type="button" class="modality-pill is-active" data-modality="text" role="radio" aria-checked="true">Text</button>
  <button type="button" class="modality-pill" data-modality="audio" role="radio" aria-checked="false">Audio</button>
  <button type="button" class="modality-pill" data-modality="video" role="radio" aria-checked="false">Video</button>
</div>
```

Immediately *after* the two-textarea block, add the dropzone pair:

```html
<div class="dropzone-row" id="dropzoneRow" hidden>
  <label class="dropzone" data-slot="a">
    <input type="file" id="fileA" hidden>
    <div class="dropzone-label">Drop stimulus A here, or click to choose</div>
    <div class="dropzone-filename" id="fileAName"></div>
  </label>
  <label class="dropzone" data-slot="b">
    <input type="file" id="fileB" hidden>
    <div class="dropzone-label">Drop stimulus B here, or click to choose</div>
    <div class="dropzone-filename" id="fileBName"></div>
  </label>
</div>
```

**Step 7.3** — In the existing `<script>` block at the bottom, add (before the closing `}` of the IIFE, if there is one; otherwise at the end):

```js
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
const AUDIO_ACCEPT = '.wav,.mp3,.flac,.ogg,audio/wav,audio/mpeg,audio/flac,audio/ogg';
const VIDEO_ACCEPT = '.mp4,.avi,.mkv,.mov,.webm,video/mp4,video/x-msvideo,video/x-matroska,video/quicktime,video/webm';

const modalityPills = document.querySelectorAll('.modality-pill');
const textareaCards = document.querySelectorAll('.textarea-card');
const dropzoneRow = document.getElementById('dropzoneRow');
const fileA = document.getElementById('fileA');
const fileB = document.getElementById('fileB');
const fileAName = document.getElementById('fileAName');
const fileBName = document.getElementById('fileBName');
let activeModality = 'text';

function setModality(m) {
  activeModality = m;
  modalityPills.forEach(p => {
    const on = p.dataset.modality === m;
    p.classList.toggle('is-active', on);
    p.setAttribute('aria-checked', on ? 'true' : 'false');
  });
  const isText = m === 'text';
  textareaCards.forEach(el => el.hidden = !isText);
  dropzoneRow.hidden = isText;
  const accept = m === 'audio' ? AUDIO_ACCEPT : VIDEO_ACCEPT;
  fileA.accept = accept;
  fileB.accept = accept;
}

modalityPills.forEach(p => p.addEventListener('click', () => setModality(p.dataset.modality)));

document.querySelectorAll('.dropzone').forEach(zone => {
  const slot = zone.dataset.slot;
  const input = slot === 'a' ? fileA : fileB;
  const label = slot === 'a' ? fileAName : fileBName;
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('is-dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('is-dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('is-dragover');
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      label.textContent = input.files[0].name;
    }
  });
  input.addEventListener('change', () => {
    label.textContent = input.files[0]?.name || '';
  });
});
```

**Step 7.4** — Update the form submission handler. Find the existing submit handler (it POSTs JSON to `/api/diff/start`). Replace its body with this dispatch pattern, or wrap it:

```js
async function onFormSubmit(event) {
  event.preventDefault();
  if (activeModality === 'text') {
    return submitTextDiff(event);  // existing logic renamed
  }
  const a = fileA.files[0], b = fileB.files[0];
  if (!a || !b) {
    showToast('Choose two files before launching.', { kind: 'warn', durationMs: 3000, key: 'upload' });
    return;
  }
  if (a.size > MAX_UPLOAD_BYTES || b.size > MAX_UPLOAD_BYTES) {
    showToast('Each file must be 100 MB or smaller.', { kind: 'error', durationMs: 4000, key: 'upload' });
    return;
  }
  const body = new FormData();
  body.append('file_a', a);
  body.append('file_b', b);
  const resp = await fetch('/api/diff/upload', { method: 'POST', body });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: resp.statusText }));
    showToast(`Upload failed: ${detail.detail}`, { kind: 'error', durationMs: 5000, key: 'upload' });
    return;
  }
  const { job_id } = await resp.json();
  window.location.href = `/run.html?job=${encodeURIComponent(job_id)}`;
}
```

Rename the existing JSON-submission function to `submitTextDiff` and attach `onFormSubmit` as the form's submit listener.

**Step 7.5** — Manual verification. Open `http://127.0.0.1:8000/launch` in the browser. Click each pill in turn. Confirm:
- Text mode shows textareas, not dropzones.
- Audio mode shows dropzones; file input accepts audio only; dragging a .mp4 on an audio dropzone shows browser's "not allowed" cursor.
- Dropping a file shows its name in the dropzone.
- Submitting >100 MB shows the toast and does not POST.

**Commit:**

```bash
git add frontend_new/input.html
git commit -m "feat: modality toggle + file dropzones on /launch"
```

---

# Task 8 — Modality-aware labels on `/run` deep scope

**Goal:** The run page renders status strings from the backend. Two new status codes (`decoding_audio`, `decoding_video`) need labels; everything else flows through because the backend now emits modality-aware copy in the existing `transcribing_*` / `predicting_*` messages.

**File:** `frontend_new/run.html`

**Step 8.1** — Search for the status-code-to-label map (likely `STATUS_LABELS`, `STEP_LABELS`, or similar). Add entries:

```js
// in the status-label map
decoding_audio:  'Decoding audio features',
decoding_video:  'Decoding video + extracting frames',
```

If the map also drives icons or colors for each step, mirror what `converting_text_to_speech` has.

**Step 8.2** — Visual verification: submit an audio diff (Task 9), watch the `/run.html` deep scope. The top step should read "Decoding audio features" instead of "Converting text to speech".

**Commit:**

```bash
git add frontend_new/run.html
git commit -m "feat: modality-aware step labels on /run"
```

---

# Task 9 — End-to-end smoke: audio pair

No code changes — verification only. Generate two short WAV files (macOS):

```bash
say -o /tmp/sample_a.wav --file-format=WAVE --data-format=LEI16 "The Federal Reserve raised interest rates today to combat persistent inflation in the services sector."
say -o /tmp/sample_b.wav --file-format=WAVE --data-format=LEI16 "Smoking kills. Every cigarette shortens your life. Quit today and your lungs heal within weeks."
```

Submit:

```bash
curl -s -X POST http://127.0.0.1:8000/api/diff/upload \
  -F "file_a=@/tmp/sample_a.wav" \
  -F "file_b=@/tmp/sample_b.wav" | python3 -m json.tool
```

Capture the `job_id`. Poll:

```bash
JOB_ID=<from response>
while true; do
  line=$(curl -s http://127.0.0.1:8000/api/diff/status/$JOB_ID | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['status'], d.get('message',''))")
  echo "$(date +%H:%M:%S) $line"
  [[ "$line" == done* || "$line" == failed* ]] && break
  sleep 15
done
```

Expected sequence: `queued → decoding_audio → transcribing_version_a → predicting_version_a → transcribing_version_b → predicting_version_b → computing_brain_contrast → done`. Runtime on Apple Silicon MPS: 10-15 min.

Open `http://127.0.0.1:8000/results.html?job=$JOB_ID`. Brain, trade-off axis, dimension chart, recall card should all render. `meta.modality` in the JSON response should be `"audio"`.

---

# Task 10 — End-to-end smoke: video pair

No code changes. Generate two synthetic clips:

```bash
ffmpeg -f lavfi -i "testsrc=duration=30:size=640x360:rate=24" -f lavfi -i "sine=frequency=440:duration=30" \
  -c:v libx264 -c:a aac -y /tmp/clip_a.mp4
ffmpeg -f lavfi -i "testsrc2=duration=30:size=640x360:rate=24" -f lavfi -i "sine=frequency=880:duration=30" \
  -c:v libx264 -c:a aac -y /tmp/clip_b.mp4
```

Submit via the same curl pattern as Task 9 (swap paths). Expected sequence includes `decoding_video` at the top. Runtime 15-25 min. Before this submission, verify `curl http://127.0.0.1:8000/api/preflight | python3 -m json.tool` shows `video_extractor.ok: true` — otherwise the first video diff will download 6 GB inline.

---

# Task 11 — Push + open PR

**Step 11.1** — Verify remote:

```bash
cd "/Users/ishita/Downloads/Work code/Brain Diff - all in/braindiff_v2"
git remote -v
```

If `origin` does not point at `https://github.com/ishita7077/braindiff-all-in.git`, set it:

```bash
git remote set-url origin https://github.com/ishita7077/braindiff-all-in.git
# If origin does not exist:
# git remote add origin https://github.com/ishita7077/braindiff-all-in.git
```

**Step 11.2** — Push feature branch:

```bash
git checkout -b feat/audio-video-input
git push -u origin feat/audio-video-input
```

**Step 11.3** — Open PR:

```bash
gh pr create --title "Audio + video input support" --body "$(cat <<'EOF'
## Summary
- Adds audio (.wav .mp3 .flac .ogg) and video (.mp4 .avi .mkv .mov .webm) stimuli alongside text
- New `POST /api/diff/upload` multipart endpoint: 100 MB per-file cap, files persisted under `cache/uploads/<job_id>/`
- `TribeService` gains `audio_to_predictions` + `video_to_predictions`
- Media clips longer than 30s are truncated server-side to the first 30s; warning attached to the job result
- Text requires A and B within 20 characters of each other; audio/video within 5 seconds
- Preflight pre-pulls `facebook/vjepa2-vitg-fpc64-256` so first video diff doesn't cold-start for 5 min
- `/launch` gets a Text/Audio/Video modality toggle + file dropzone pair
- `/run` shows modality-aware deep-scope step labels

## Test plan
- [ ] `BRAIN_DIFF_SKIP_STARTUP=1 PYTHONPATH=. .venv/bin/pytest tests/ -q` passes
- [ ] Text diff end-to-end regression (identical + different texts)
- [ ] Audio diff end-to-end with two `say`-generated .wav files
- [ ] Video diff end-to-end with two 30s `ffmpeg testsrc` clips
- [ ] Upload >100 MB returns 413 with clear detail
- [ ] Mixed-modality upload (a.wav + b.mp4) returns 400 with clear detail
- [ ] Cross-tolerance stimuli (e.g. 10s + 28s audio) return INPUT_REJECTED job status
- [ ] `/api/preflight` reports `video_extractor.ok: true`

## Deferred (tracked separately)
- Cleanup of `cache/uploads/<job_id>/` after jobs complete — no reaper yet

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

# Verification checklist (run at the end)

Before declaring done, confirm:

- [ ] `BRAIN_DIFF_SKIP_STARTUP=1 PYTHONPATH=. .venv/bin/pytest tests/ -q` — all green
- [ ] Server starts, `/api/ready` returns `ok: true`, `model_loaded: true`
- [ ] `/api/preflight` shows `video_extractor.ok: true`
- [ ] Text diff (different texts) completes and returns a populated result
- [ ] Audio diff completes and returns a populated result with `meta.modality = "audio"`
- [ ] Video diff completes and returns a populated result with `meta.modality = "video"`
- [ ] 100 MB cap enforced (413 response, toast on frontend)
- [ ] 30s truncation warning attached to the result when input was longer
- [ ] Similarity mismatch rejected with INPUT_REJECTED
- [ ] `/launch` modality toggle visually clean in both dark and light themes
- [ ] No comments were added beyond one-liner "why" comments (if any)
- [ ] No unrelated files modified (`git log --name-only` shows only the listed files)
- [ ] 11 commits, each with the messages specified above

If any of these fails, fix before pushing.
