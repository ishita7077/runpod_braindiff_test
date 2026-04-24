# Launch Checklist

- [ ] Runpod worker image built from `runpod_worker/Dockerfile`
- [ ] Runpod endpoint healthy for text/audio/video URL payloads
- [ ] Vercel env vars configured from `.env.example`
- [ ] Turnstile verification working server-side
- [ ] Upstash daily + burst limits enforced
- [ ] Blob URLs cleaned after completion
- [ ] End-to-end checks from `TESTING.md` pass on preview

## Production rollout order

1. Deploy Runpod worker image.
2. Validate Runpod requests tab payloads.
3. Deploy Vercel preview with env vars.
4. Full E2E run on preview.
5. Promote preview to production.
6. Point domain to Vercel production.
