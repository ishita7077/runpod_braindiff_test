const DAY_SECONDS = 24 * 60 * 60;

function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function optionalInt(name, fallback) {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function optionalTrim(name) {
  const v = process.env[name];
  return typeof v === "string" ? v.trim() : "";
}

/** Both site + secret must be set, or Turnstile is off (local / private testing). */
function turnstileEnabled() {
  return !!(optionalTrim("TURNSTILE_SITE_KEY") && optionalTrim("TURNSTILE_SECRET_KEY"));
}

/**
 * Safe for GET /api/config/public — only Turnstile **public** fields.
 * Do not use runtimeConfig() there: it requires Runpod/Redis/Blob.
 */
function publicShellConfig() {
  const site = optionalTrim("TURNSTILE_SITE_KEY");
  const on = turnstileEnabled();
  return {
    turnstileSiteKey: on ? site : "",
    turnstileRequired: on
  };
}

function runtimeConfig() {
  const tsOn = turnstileEnabled();
  return {
    runpodApiKey: required("RUNPOD_API_KEY"),
    runpodEndpointId: required("RUNPOD_ENDPOINT_ID"),
    turnstileEnabled: tsOn,
    turnstileSecretKey: tsOn ? required("TURNSTILE_SECRET_KEY") : "",
    turnstileSiteKey: tsOn ? required("TURNSTILE_SITE_KEY") : "",
    blobReadWriteToken: required("BLOB_READ_WRITE_TOKEN"),
    upstashRedisRestUrl: required("UPSTASH_REDIS_REST_URL"),
    upstashRedisRestToken: required("UPSTASH_REDIS_REST_TOKEN"),
    limits: {
      textPerDay: optionalInt("RATE_LIMIT_TEXT_PER_DAY", 10),
      mediaPerDay: optionalInt("RATE_LIMIT_MEDIA_PER_DAY", 5),
      burstPerMinute: optionalInt("RATE_LIMIT_BURST_PER_MINUTE", 3)
    },
    blobDeleteAfterSeconds: optionalInt("BLOB_DELETE_AFTER_SECONDS", DAY_SECONDS)
  };
}

module.exports = {
  runtimeConfig,
  publicShellConfig,
  turnstileEnabled,
  DAY_SECONDS
};
