# BrainDiff / TRIBEv2 — known failure modes & UI guardrails

This is the single canonical list of things that can go wrong with a text → text
diff run, why they happen, and how each one is surfaced to the user. Keep this
in sync with:

- `frontend_new/input.html`   (pre-submit validation, soft warnings + hard blocks)
- `frontend_new/run.html`     (ERROR_TIPS map — in-run error banner copy)
- `backend/api.py`            (error codes produced by `_run_diff_job`)
- `backend/model_service.py`  (exception → error-code mapping in `text_to_predictions`)
- `tribev2/tribev2/demo_utils.py` (TTS + WhisperX pipeline for the text path)
- `tribev2/tribev2/eventstransforms.py` (WhisperX language hard-coded to English)

## Product decision: English only

BrainDiff only accepts English text. The rationale:

- `tribev2.eventstransforms.ExtractWordsFromAudio.language` is hard-coded to
  `"english"` — non-English transcription would be wrong anyway.
- Upstream TRIBEv2 calls `langdetect.detect(text)` and passes the result to
  `gTTS(..., lang=...)`. langdetect returns codes gTTS does not support on short
  or ambiguous inputs (e.g. `so`, `cy`), which aborted whole jobs in practice.

We handle this in two places:

1. **Frontend** (`input.html`): the `NON_ENGLISH` rule is a **hard block** — if
   either version has < 60% ASCII letters (given ≥ 20 chars to judge), submit
   is disabled and the error banner explains why.
2. **Backend** (`backend/model_service.py::_patch_tribev2_force_english`): at
   server startup we replace `langdetect.detect` with a function that always
   returns `"en"`. TRIBEv2 re-imports `detect` inside `get_events` on every
   call, so the patch is live without touching the upstream `tribev2/` source.

## Pipeline shape (text input)

```
user text (English-only, enforced at UI)
  → gTTS(text, lang="en")             # langdetect monkey-patched to return "en"
  → audio.mp3
  → WhisperX (hard-coded English)     # eventstransforms.ExtractWordsFromAudio
  → word events DataFrame
  → TribeModel.predict → per-TR brain activations
  → backend scorer / differ → dimension scores + vertex delta
```

Any break in that chain becomes a backend error code that `run.html` renders.

---

## 1. Input-shape failures — caught pre-submit on `input.html`

These never reach the backend if the UI does its job. The submit button
disables for **hard** conditions; **soft** conditions show an orange warning
banner but still let the user proceed.

| severity | code                  | trigger                                                            | copy shown to user                                                                 |
|---------:|-----------------------|--------------------------------------------------------------------|------------------------------------------------------------------------------------|
| **hard** | `EMPTY`               | textarea is blank or whitespace-only after trim                    | "Both versions need some text."                                                   |
| **hard** | `OVER_LIMIT`          | char count > 5000 (also enforced by `maxlength` attribute)         | "Max 5,000 characters per version."                                               |
| **hard** | `NON_ENGLISH`         | < 60% of non-space chars are ASCII letters (given ≥ 20 chars)      | "BrainDiff currently supports English text only. Please paste English for both versions." |
| soft     | `TOO_SHORT`           | `< 15 chars` **or** `< 3 words` in either version                  | "Very short text produces noisy contrasts. Add a couple more sentences."          |
| soft     | `LIGHT`               | `3–8 words` in either version                                      | "Short inputs work but amplify randomness. Consider 15+ words per side."          |
| soft     | `LENGTH_SKEW`         | `max(lenA, lenB) / min(lenA, lenB) >= 10`                          | "One version is much longer than the other — the contrast will be length-biased." |
| soft     | `IDENTICAL`           | A and B equal after trim + whitespace collapse                     | "Both versions are identical — you'll get an all-zero contrast."                  |
| soft     | `LINK_HEAVY`          | URL characters make up > 25% of the text                           | "URLs get read aloud letter-by-letter — the contrast may not mean much."          |
| soft     | `NO_LETTERS`          | text has zero `[A-Za-z]` letters (emoji / digits only)             | "No words to speak — the TTS step will produce silence."                          |
| soft     | `NO_SENTENCES`        | > 40 words but zero `.!?` terminators                              | "Long text with no sentence breaks may throw off word alignment."                 |

All `canSubmit()` checks run on every `input` event and on focus/blur. Soft
warnings don't block submission; they populate a soft banner above the button
and stay visible until the user edits the text or submits.

---

## 2. Pipeline failures — produced by the backend, shown on `run.html`

Each one is returned in `GET /api/diff/status/{job_id}` as:

```json
{ "status": "error",
  "error": { "code": "…", "message": "…", "request_id": "…" } }
```

`run.html` maps the code to a short remediation tip (`ERROR_TIPS`). Keep this
table in sync with that map.

| code                    | where it's raised                                             | typical cause                                                                       | remediation copy                                                                  |
|-------------------------|---------------------------------------------------------------|-------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| `FFMPEG_REQUIRED`       | `TribeService._ensure_ffmpeg_on_path`, text path exception    | No ffmpeg binary on PATH / `IMAGEIO_FFMPEG_EXE` unset and imageio_ffmpeg has no bundled arm64 binary | "Install ffmpeg (`brew install ffmpeg`) or set IMAGEIO_FFMPEG_EXE."             |
| `HF_AUTH_REQUIRED`      | `TribeService.text_to_predictions` exception dispatch         | No Hugging Face login, or token lacks approval for `meta-llama/Llama-3.2-3B`       | "Run `huggingface-cli login` with an approved token."                             |
| `WHISPERX_FAILED`       | idem                                                          | CTranslate2 compute-type / device mismatch (e.g. `float16` on CPU), MPS not supported | "On Apple Silicon, WhisperX must run on CPU. Check `TRIBEV2_WHISPERX_DEVICE`."   |
| `UVX_REQUIRED`          | idem                                                          | WhisperX invocation needs `uvx` and it's missing                                    | "Install uv: `pip install uv`."                                                   |
| `LLAMA_LOAD_FAILED`     | idem                                                          | Llama text encoder OOM / dtype mismatch                                             | "Check free RAM / VRAM, try `BRAIN_DIFF_TEXT_BACKEND=cpu`."                      |
| `ATLAS_MAPPING_ERROR`   | `backend.brain_regions`                                       | HCP atlas files missing or mis-versioned under `atlases/`                           | "Verify atlas files under `atlases/`."                                            |
| `DIFF_JOB_FAILED`       | catch-all in `_run_diff_job`                                  | Any unhandled exception inside the pipeline                                         | "The pipeline raised an exception. Try longer, clearly-English inputs."          |
| `NOT_FOUND` *(client)*  | 404 on `/api/diff/status/{id}`                                | Job id expired, server restart dropped in-memory job                                | "This job id is unknown. It may have expired on the server."                     |

### Warnings that are NOT errors

The backend also returns a `warnings: []` list inside the successful result
(`_warnings_for_input`). These are advisory labels shown in the results meta
card; the run still finishes.

- `"Very short text may produce unreliable results"` (< 3 words either side)
- `"Large length difference may affect comparison"` (≥ 10× ratio)

---

## 3. When A and B are identical

`backend/api.py::_run_diff_job` short-circuits identical inputs to an all-zero
diff (not an error). The frontend should call this out explicitly rather than
letting the user stare at a flat map.

---

## 4. Hidden WhisperX language assumption (now consistent with product)

`tribev2.eventstransforms.ExtractWordsFromAudio.language` is hard-coded to
`"english"`. Since BrainDiff is English-only (§ product decision above), this
is fine — we never mismatch the TTS language against the transcription
language. The `NON_ENGLISH` hard rule on `input.html` enforces it.

---

## 5. Things that ARE supported (avoid over-warning)

- Mixed punctuation, em-dashes, curly quotes — fine.
- All-caps text — fine; gTTS handles it.
- Up to 5,000 characters — fine (but slow; ~2-12 min per diff).
- Line breaks, multiple paragraphs — fine.
- Numbers mixed with text (e.g. "3 reasons why…") — fine.

Don't warn about any of these.
