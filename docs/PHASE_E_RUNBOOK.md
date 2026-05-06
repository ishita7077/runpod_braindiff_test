# Phase E — Production deploy runbook

This runbook is the green-light checklist for shipping Phases A–D to
production. Every step is necessary; the order matters.

## 0. Preconditions

Before starting:

- [ ] `claude/general-session-YI1wI` is up-to-date with origin and CI is green.
- [ ] Phase D evaluation has been run on RunPod (see `docs/PHASE_D_RUNBOOK.md`)
      and the report shows `mean_fallback_rate < 0.10` and
      `brief_present_rate >= 0.80` for `gemma-3-1b-it`.
- [ ] You have RunPod admin and Vercel deploy permissions.
- [ ] Required env vars are set on the worker:
      `HF_TOKEN`, `TRIBEV2_REVISION`, `BRAIN_DIFF_ATLAS_DIR`,
      `RUNPOD_MEDIA_MAX_MB`, plus the new ones:
      `BRAIN_DIFF_CONTENT_MODEL` (default `google/gemma-3-1b-it`),
      `BRAIN_DIFF_CONTENT_DTYPE` (default `bfloat16`),
      `BRAIN_DIFF_GPU_JOB_CONCURRENCY` (default `1` — keep `1` until
      Phase E.5 measurements clear a bump).

## 1. Build the worker image

```bash
docker build -f runpod_worker/Dockerfile -t braindiff-worker:phase-e .
docker push <your-registry>/braindiff-worker:phase-e
```

## 2. Deploy the RunPod endpoint

Update the RunPod endpoint to the new image. **Keep `max_workers >= 2`**;
the GPU job lock is now process-local so endpoint-level concurrency is the
only safe way to handle multiple jobs.

## 3. Deploy the Vercel preview

```bash
npm run vercel:deploy
```

Note the preview URL.

## 4. Smoke

```bash
# Vercel preview wiring
npm run smoke:preview

# RunPod end-to-end
RUNPOD_API_KEY=... RUNPOD_ENDPOINT_ID=... npm run smoke:runpod
```

A real text + audio + video job, each end-to-end. Inspect each response:

- [ ] `meta.content_audit.schema_version === "content_audit.v1"`
- [ ] `meta.content_audit.fallback_rate < 0.20`
- [ ] `meta.content_audit.input_mapping` lists no `unmapped_dimensions`
- [ ] `meta.content_audit.input_mapping` lists no `filled_flat_systems`
- [ ] `meta.content_model.id === "google/gemma-3-1b-it"` (or the env override)
- [ ] `meta.gpu_audit.snapshots[].peak_allocated_mb` leaves at least
      `0.20 * total_mb` headroom on every snapshot
- [ ] `meta.results_content_error` is **absent**
- [ ] `result.results_content.schema_version === "results_content.v1"`
- [ ] `result.results_content.slots.analysis_brief.source === "llm"` and
      its `value.thesis` is non-empty

## 5. Two-job concurrency smoke (optional, but unblocks scaling)

If you intend to run with `max_workers >= 2` and want to test the lock:

```bash
node scripts/runpod-concurrency-smoke.mjs --count 2 \
  --video-a <URL_A> --video-b <URL_B>
```

(That script doesn't ship today; the moral equivalent is to launch two
RunPod jobs in parallel against the same endpoint and confirm no CUDA
OOM, no content_pipeline_returned_none, and that endpoint scaled out to
two workers rather than two jobs sharing one process.)

## 6. Promote to production

Promote to the production endpoint **only after**:

- [ ] every smoke item in §4 passed
- [ ] §5 ran cleanly OR you accept single-worker production
- [ ] the rich page renders the analysis_brief block (Frame 01.5) on a real
      job — open `/results.html?jobId=<id>` and look for the "Frame 01.5 ·
      Analysis Brief" eyebrow above the chord progression

## 7. Sign-off — non-negotiable acceptance checklist

This mirrors the plan's final checklist; tick before announcing rollout:

- [ ] `attention_salience` maps to `attention` in rich content (Phase A.1 + fixture 05)
- [ ] `results_content` is rendered as the primary result (Phase B + frontend smokes)
- [ ] `results.html` chord detail has no `ReferenceError` (Phase A.2)
- [ ] Content model logs and metadata say Gemma / content model, not LLaMA (Phase A.5)
- [ ] Slot fallback reasons are visible in `content_audit` (Phase A.3)
- [ ] Gemma gets a compact evidence packet, not raw noisy data (Phase C.2)
- [ ] Gemma produces `analysis_brief` before section copy (Phase C.7)
- [ ] Validators repair model output before fallback (Phase C.5)
- [ ] Every recommendation cites real evidence (Phase C.6 grounding validator)
- [ ] GPU memory snapshots exist (Phase A.4)
- [ ] In-process concurrency is locked to 1 unless proven safe (Phase E.1)
- [ ] Endpoint concurrency is tested with 2 jobs (Phase E §5)
- [ ] Vercel preview smoke passes (§4)
- [ ] RunPod smoke passes (§4)
- [ ] Production deploy only after preview result quality is manually reviewed

## 8. Rollback

If §4 fails on the new image:

```bash
# point the endpoint back at the previous image tag
runpodctl endpoint update <id> --image <your-registry>/braindiff-worker:phase-d
```

The pre-Phase-A frontend assets cache in Vercel — if the rich page
breaks, the legacy debug pages survive at their old URLs and the run
page can be opened with `?legacy=1` to pin the old route.
