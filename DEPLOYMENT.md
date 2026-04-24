# BrainDiff Deployment (Vercel + Runpod)

This repo keeps the existing BrainDiff app/UI and adds:

- Vercel adapter API routes (`api/*`)
- Runpod serverless worker (`runpod_worker/*`)

## Runpod worker

Entrypoint: `runpod_worker/handler.py`  
Dockerfile: `runpod_worker/Dockerfile`

Runpod request input shape:

- text:
  - `mode: "text"`
  - `text_a`, `text_b`
- media:
  - `mode: "audio"` or `mode: "video"`
  - `media_url_a`, `media_url_b`

## Vercel adapter routes

- `POST /api/diff/start`
- `GET /api/diff/status/:jobId`
- `POST /api/blob/upload`
- `GET /api/config/public`

## Required env vars (Vercel)

- `RUNPOD_API_KEY`
- `RUNPOD_ENDPOINT_ID`
- `TURNSTILE_SITE_KEY`
- `TURNSTILE_SECRET_KEY`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `BLOB_READ_WRITE_TOKEN`

Optional:

- `RATE_LIMIT_TEXT_PER_DAY` (default 10)
- `RATE_LIMIT_MEDIA_PER_DAY` (default 5)
- `RATE_LIMIT_BURST_PER_MINUTE` (default 3)
- `BLOB_DELETE_AFTER_SECONDS` (default 86400)

## Required env vars (Runpod worker)

- `TRIBEV2_REVISION`
- `BRAIN_DIFF_ATLAS_DIR`
- any existing HF/TRIBE auth/runtime vars used locally

## Deploy order

1. Build and push Runpod worker image.
2. Create/verify Runpod serverless endpoint.
3. Set Vercel env vars.
4. Deploy Vercel preview.
5. Run end-to-end checks from `TESTING.md`.
6. Promote to production and connect domain.
