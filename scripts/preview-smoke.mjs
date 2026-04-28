#!/usr/bin/env node
/**
 * Minimal post-deploy check: GET /api/config/public
 *
 *   VERCEL_PREVIEW_URL=https://....vercel.app node scripts/preview-smoke.mjs
 */

import process from "node:process";

const base = (process.env.VERCEL_PREVIEW_URL || "").replace(/\/$/, "");
if (!base) {
  console.error("Set VERCEL_PREVIEW_URL to your deployment origin (no trailing slash).");
  process.exit(2);
}

async function main() {
  const url = `${base}/api/config/public`;
  const res = await fetch(url);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    console.error(`GET ${url} -> ${res.status}`, data);
    process.exit(1);
  }
  if (typeof data.turnstileRequired !== "boolean") {
    console.error("Expected JSON.turnstileRequired (boolean) from /api/config/public", data);
    process.exit(1);
  }
  console.log(
    "preview-smoke OK: turnstileRequired=" +
      data.turnstileRequired +
      (data.turnstileSiteKey ? " (site key present)" : " (no site key)")
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
