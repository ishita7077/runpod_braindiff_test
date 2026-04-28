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

## Vercel upload size

The repo includes a local Python `.venv` and caches that must **not** be uploaded. [`.vercelignore`](.vercelignore) excludes those paths; keep it updated if you add large local-only directories.

## Vercel adapter routes

- `POST /api/diff/start`
- `GET /api/diff/status/:jobId`
- `POST /api/blob/upload`
- `GET /api/config/public`

## Required env vars (Vercel)

- `RUNPOD_API_KEY`
- `RUNPOD_ENDPOINT_ID`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `BLOB_READ_WRITE_TOKEN`

Optional:

- `TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY` — set **both** to enable Cloudflare Turnstile; omit **both** to disable (local/private testing)
- `RATE_LIMIT_TEXT_PER_DAY` (default 10)
- `RATE_LIMIT_MEDIA_PER_DAY` (default 5)
- `RATE_LIMIT_BURST_PER_MINUTE` (default 3)
- `BLOB_DELETE_AFTER_SECONDS` (default 86400)

## Required env vars (Runpod worker)

- `TRIBEV2_REVISION`
- `BRAIN_DIFF_ATLAS_DIR`
- `HUGGINGFACE_HUB_TOKEN` (if Tribe/model weights need authenticated download)
- any other HF/TRIBE auth/runtime vars you use locally

## Deploy order

1. Build and push Runpod worker image.
2. Create/verify Runpod serverless endpoint.
3. Set Vercel env vars.
4. Deploy Vercel preview.
5. Run end-to-end checks from `TESTING.md`.
6. Promote to production and connect domain.

## Build Runpod image without local Docker

Push this repo to GitHub, then run the workflow **Runpod worker Docker image** (`.github/workflows/runpod-worker-docker.yml`). It publishes to `ghcr.io/<owner>/<repo>:runpod-latest` (and a `runpod-<sha>` tag). In Runpod, point the serverless template at that image (make the GHCR package public or configure a pull secret).

## Vercel CLI login and deploy

From the repo root:

1. **Device login (interactive):**

   ```bash
   npm install
   npm run vercel:login
   ```

   Open [https://vercel.com/oauth/device](https://vercel.com/oauth/device) and enter the **user_code** printed in the terminal (it expires quickly; each run generates a new code).

2. **Token login (CI or headless):** create a token at [Vercel Account Tokens](https://vercel.com/account/tokens), then:

   ```bash
   npx vercel login --token YOUR_TOKEN
   ```

3. **Link and deploy:**

   ```bash
   npm run vercel:link
   npm run vercel:deploy
   ```

4. **Post-deploy smoke (public config only):** after you have a preview URL:

   ```bash
   VERCEL_PREVIEW_URL=https://your-preview.vercel.app npm run smoke:preview
   ```

## Runpod API smoke (same payloads as Requests tab)

With `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` set:

```bash
npm run smoke:runpod
```

Text always runs. For audio/video, set public test URLs (or pass CLI flags — see `scripts/runpod-smoke.mjs` header).
