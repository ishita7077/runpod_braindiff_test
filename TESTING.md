# Testing Guide

## Runpod Requests tab payloads

### Text

```json
{
  "input": {
    "mode": "text",
    "text_a": "AI policy should focus on transparency, safety, and measured rollout.",
    "text_b": "AI policy must move fast to preserve innovation while managing risk."
  }
}
```

### Audio URLs

```json
{
  "input": {
    "mode": "audio",
    "media_url_a": "https://example.com/a.wav",
    "media_url_b": "https://example.com/b.wav"
  }
}
```

### Video URLs

```json
{
  "input": {
    "mode": "video",
    "media_url_a": "https://example.com/a.mp4",
    "media_url_b": "https://example.com/b.mp4"
  }
}
```

## Automated Runpod smoke (API)

Same JSON shapes as above, via Runpod Serverless HTTP API:

```bash
export RUNPOD_API_KEY=...
export RUNPOD_ENDPOINT_ID=...
npm run smoke:runpod
```

Optional env (public HTTPS URLs the worker can download):

- `RUNPOD_SMOKE_AUDIO_URL_A`, `RUNPOD_SMOKE_AUDIO_URL_B`
- `RUNPOD_SMOKE_VIDEO_URL_A`, `RUNPOD_SMOKE_VIDEO_URL_B`

Or pass flags: `node scripts/runpod-smoke.mjs --audio-a URL --audio-b URL` (and `--video-a` / `--video-b`).

## Vercel preview checks

1. Open `/launch`
2. If `TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY` are set, confirm Turnstile loads; otherwise bot check is off
3. Submit text comparison -> `/api/diff/start`
4. Confirm `/run` polls `/api/diff/status/:jobId`
5. Confirm `/results` renders output
6. Repeat with audio/video upload flow (Blob upload then `/api/diff/start` with `media_url_*`)
7. Confirm rate limits:
   - text: 10/day/IP
   - media: 5/day/IP
   - burst: short per-minute limit

Quick non-interactive check after deploy (Turnstile not exercised):

```bash
VERCEL_PREVIEW_URL=https://your-preview.vercel.app npm run smoke:preview
```
