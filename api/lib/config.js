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

function runtimeConfig() {
  return {
    runpodApiKey: required("RUNPOD_API_KEY"),
    runpodEndpointId: required("RUNPOD_ENDPOINT_ID"),
    turnstileSecretKey: required("TURNSTILE_SECRET_KEY"),
    turnstileSiteKey: required("TURNSTILE_SITE_KEY"),
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
  DAY_SECONDS
};
