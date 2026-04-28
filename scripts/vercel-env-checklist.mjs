#!/usr/bin/env node
/**
 * Env names required by Vercel serverless routes (see api/lib/config.js).
 * Worker-only vars (TRIBEV2_*, BRAIN_DIFF_*, RUNPOD_MEDIA_MAX_MB) belong on Runpod, not Vercel.
 */
const required = [
  "RUNPOD_API_KEY",
  "RUNPOD_ENDPOINT_ID",
  "UPSTASH_REDIS_REST_URL",
  "UPSTASH_REDIS_REST_TOKEN",
  "BLOB_READ_WRITE_TOKEN"
];
const optionalTurnstile = [
  "TURNSTILE_SITE_KEY",
  "TURNSTILE_SECRET_KEY"
];
const optional = [
  "RATE_LIMIT_TEXT_PER_DAY",
  "RATE_LIMIT_MEDIA_PER_DAY",
  "RATE_LIMIT_BURST_PER_MINUTE",
  "BLOB_DELETE_AFTER_SECONDS"
];
console.log("Vercel → Project → Settings → Environment Variables\n");
console.log("Required:\n");
for (const k of required) console.log(`  - ${k}`);
console.log(
  "\nTurnstile (optional — omit **both** keys to disable bot check for local/private testing):\n"
);
for (const k of optionalTurnstile) console.log(`  - ${k}`);
console.log("\nOther optional (defaults in api/lib/config.js if unset):\n");
for (const k of optional) console.log(`  - ${k}`);
console.log(
  "\nRunpod worker env (see DEPLOYMENT.md): TRIBEV2_REVISION, BRAIN_DIFF_ATLAS_DIR, HUGGINGFACE_HUB_TOKEN, etc.\n"
);
