# Launch Checklist

## Before production (Turnstile)

During **private / local testing**, Turnstile can stay **off** by leaving **`TURNSTILE_SITE_KEY`** and **`TURNSTILE_SECRET_KEY`** unset (see `DEPLOYMENT.md`).

**Before any production deployment:** turn bot protection back **on** — set **both** Turnstile env vars in Vercel (and any other prod host), redeploy, and confirm `/launch` shows the widget and `/api/diff/start` rejects requests without a valid token.

---

- [ ] Runpod worker image built from `runpod_worker/Dockerfile` (local Docker **or** GitHub Actions workflow **Runpod worker Docker image**)
- [ ] Runpod endpoint healthy for text/audio/video URL payloads
- [ ] Vercel env vars configured from `.env.example`
- [ ] If Turnstile keys are set, verification works server-side (omit both keys to skip)
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
