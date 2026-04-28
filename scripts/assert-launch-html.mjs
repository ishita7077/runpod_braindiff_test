#!/usr/bin/env node
/**
 * Static checks that /launch (input.html) wires text + Blob media + API routes.
 * Turnstile is optional: loads only when server sets both keys (see api/lib/config.js).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const htmlPath = path.join(__dirname, "..", "frontend_new", "input.html");
const html = fs.readFileSync(htmlPath, "utf8");
const need = [
  "/api/config/public",
  "/api/diff/start",
  "/api/blob/upload",
  "@vercel/blob",
  "modality: 'text'",
  "modality: mode",
  'data-mode="audio"',
  'data-mode="video"',
  "turnstileRequired",
  "challenges.cloudflare.com/turnstile"
];
const missing = need.filter((s) => !html.includes(s));
if (missing.length) {
  console.error("input.html missing:", missing);
  process.exit(1);
}
console.log("assert-launch-html OK:", htmlPath);
