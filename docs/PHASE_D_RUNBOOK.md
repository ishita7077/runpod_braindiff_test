# Phase D — Content model evaluation runbook

This runbook describes how to evaluate the content pipeline against a model
ladder, using the harness in `scripts/content_eval/`. Phase D is gated on
real Gemma inference; **none of these commands run on a CPU-only machine
with confidence — you need the RunPod GPU image (or an equivalent CUDA
worker)**.

## Inventory

```
scripts/content_eval/
├── fixtures/                       # 5 hand-crafted comparisons (text + media-shaped)
│   ├── 01_personal_vs_corporate_text.json
│   ├── 02_visceral_vs_analytical.json
│   ├── 03_dense_chord_progression.json
│   ├── 04_minimal_signal.json
│   └── 05_attention_salience_legacy.json    # exercises the Phase A.1 alias
├── run_eval.py                     # runs every fixture, writes a report
└── compare_reports.py              # diffs two reports + auto promotion gate
```

Each fixture is a JSON object with the same keys
`generate_content_for_worker` accepts — no media files required, the
TRIBE-shape outputs are pre-baked. This means the harness exercises the
full Gemma + slot pipeline without re-running TRIBE.

## Step 1 — sanity check on CPU (stub backend)

Before deploying anywhere, confirm the harness wiring is healthy:

```bash
python -m scripts.content_eval.run_eval --stub --output reports/stub.json
```

Expected output: every fixture reports `"ok": true`, `schema_version =
results_content.v1`, headline + body filled (with stub fixture text),
`brief_present = false` (stub doesn't return brief JSON). This proves the
harness can drive the pipeline end-to-end — failures here are pipeline
bugs, not model-quality issues.

## Step 2 — baseline run on RunPod (Gemma 3 1B)

Deploy the worker container as usual, then on a RunPod shell:

```bash
export BRAIN_DIFF_CONTENT_MODEL=google/gemma-3-1b-it
export BRAIN_DIFF_CONTENT_DTYPE=bfloat16

python -m scripts.content_eval.run_eval \
    --output reports/eval_gemma_1b.json \
    --label "gemma-3-1b-it"
```

Expected metrics on a clean baseline (rough targets — calibrate after first
run):

| metric                      | green               | yellow                | red                      |
|-----------------------------|---------------------|-----------------------|--------------------------|
| `fixtures_ok`               | 5                   | 4                     | ≤3                       |
| `mean_fallback_rate`        | < 0.10              | 0.10–0.20             | > 0.20                   |
| `brief_present_rate`        | ≥ 0.80              | 0.50–0.80             | < 0.50                   |
| `avg_content_latency_ms`    | < 30 000            | 30 000–60 000         | > 60 000                 |
| `schema_pass_rate`          | 1.00                | 0.80–1.00             | < 0.80                   |

If yellow or red: **do NOT promote a bigger model.** Fix the prompts,
repair loop, or evidence packet first. A larger model masking pipeline
bugs is the failure mode the plan is explicitly trying to avoid.

## Step 3 — candidate runs (4B, optionally 12B quantised)

```bash
# 4B candidate
export BRAIN_DIFF_CONTENT_MODEL=google/gemma-3-4b-it
python -m scripts.content_eval.run_eval \
    --output reports/eval_gemma_4b.json \
    --label "gemma-3-4b-it"

# 12B (only if 4B fails AND VRAM headroom is healthy — see Phase E)
export BRAIN_DIFF_CONTENT_MODEL=google/gemma-3-12b-it
export BRAIN_DIFF_CONTENT_DTYPE=bfloat16
python -m scripts.content_eval.run_eval \
    --output reports/eval_gemma_12b.json \
    --label "gemma-3-12b-it"
```

Capture the GPU VRAM telemetry from the response meta (`meta.gpu_audit`)
during each run. If `peak_allocated_mb` exceeds 80 percent of `total_mb`
on any fixture, the model is too big; abort the run.

## Step 4 — diff the reports

```bash
python -m scripts.content_eval.compare_reports \
    reports/eval_gemma_1b.json \
    reports/eval_gemma_4b.json
```

The compare script applies the **automated** promotion thresholds:

* `mean_fallback_rate` may not regress by more than `+0.05`
* `avg_content_latency_ms` may not increase by more than `1.5x`
* `brief_present_rate` may not regress at all

If those gates fail, the candidate is rejected automatically.

## Step 5 — human quality review

The automated thresholds catch only the brittle failures. You **must**
read at least 3 of the 5 candidate briefs end-to-end and grade them:

| dimension                | rubric                                                                |
|--------------------------|------------------------------------------------------------------------|
| `thesis sharpness`       | does it name a real contrast? generic ("two different videos") = fail  |
| `evidence grounding`     | every recommendation cites a real timestamp from the fixture           |
| `recommendation quality` | concrete cognitive actions, no "improve clarity" / "make engaging"     |
| `voice`                  | matches voice exemplars (`backend/results/assets/voice_exemplars.json`)|

A bigger model only wins if it improves human quality by a visible margin
*and* the automated gates pass. Otherwise stay on the smaller model and
revisit prompts.

## Outputs

| file                              | what's in it                                                     |
|-----------------------------------|-------------------------------------------------------------------|
| `reports/eval_<label>.json`       | summary + per-fixture: latency, content_audit, content_model, brief |
| `reports/promotion_decision.txt`  | auto from compare; paste into the deploy ticket                  |

Commit the reports to a `reports/` directory tagged with the date —
they're the trail of evidence for any future "why did we ship X" question.
