const { Redis } = require("@upstash/redis");
const { runtimeConfig, DAY_SECONDS } = require("./config");

let redisClient = null;

function redis() {
  if (!redisClient) {
    const cfg = runtimeConfig();
    redisClient = new Redis({
      url: cfg.upstashRedisRestUrl,
      token: cfg.upstashRedisRestToken
    });
  }
  return redisClient;
}

async function verifyTurnstile({ token, ip }) {
  const cfg = runtimeConfig();
  if (!token) return { ok: false, code: "TURNSTILE_MISSING" };
  const params = new URLSearchParams();
  params.set("secret", cfg.turnstileSecretKey);
  params.set("response", token);
  if (ip) params.set("remoteip", ip);
  const res = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: params.toString()
  });
  const data = await res.json();
  if (!data.success) {
    return { ok: false, code: "TURNSTILE_FAILED", details: data["error-codes"] || [] };
  }
  return { ok: true };
}

async function applyRateLimit({ ip, type }) {
  const cfg = runtimeConfig();
  const store = redis();
  const today = new Date().toISOString().slice(0, 10);
  const dailyLimit = type === "media" ? cfg.limits.mediaPerDay : cfg.limits.textPerDay;
  const dailyKey = `ratelimit:${type}:${ip}:${today}`;
  const burstWindow = Math.floor(Date.now() / 60_000);
  const burstKey = `ratelimit:burst:${ip}:${burstWindow}`;

  const [dailyCount, burstCount] = await Promise.all([
    store.incr(dailyKey),
    store.incr(burstKey)
  ]);

  if (dailyCount === 1) {
    await store.expire(dailyKey, DAY_SECONDS);
  }
  if (burstCount === 1) {
    await store.expire(burstKey, 90);
  }

  if (dailyCount > dailyLimit) {
    return { ok: false, code: "RATE_LIMIT_DAILY", limit: dailyLimit, count: dailyCount };
  }
  if (burstCount > cfg.limits.burstPerMinute) {
    return {
      ok: false,
      code: "RATE_LIMIT_BURST",
      limit: cfg.limits.burstPerMinute,
      count: burstCount
    };
  }
  return { ok: true };
}

module.exports = {
  verifyTurnstile,
  applyRateLimit,
  redis
};
