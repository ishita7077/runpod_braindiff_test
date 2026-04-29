const crypto = require("crypto");
const { DAY_SECONDS } = require("./config");

const BLOB_PROXY_TTL_SECONDS = 6 * 60 * 60;

function blobProxySecret() {
  const token = process.env.BLOB_READ_WRITE_TOKEN;
  if (!token) throw new Error("Missing required env var: BLOB_READ_WRITE_TOKEN");
  return token;
}

function baseUrlFromRequest(req) {
  const protoHeader = req.headers["x-forwarded-proto"];
  const proto = typeof protoHeader === "string" && protoHeader.trim() ? protoHeader.trim() : "https";
  const host = req.headers.host;
  if (!host) throw new Error("Missing Host header");
  return `${proto}://${host}`;
}

function signBlobPath(pathname, expiresAt) {
  const payload = `${pathname}:${expiresAt}`;
  return crypto
    .createHmac("sha256", blobProxySecret())
    .update(payload)
    .digest("hex");
}

function createSignedBlobReadUrl(req, pathname) {
  const trimmed = String(pathname || "").trim();
  if (!trimmed) throw new Error("Missing blob pathname");
  const expiresAt = Math.floor(Date.now() / 1000) + Math.min(BLOB_PROXY_TTL_SECONDS, DAY_SECONDS);
  const sig = signBlobPath(trimmed, expiresAt);
  const url = new URL("/api/blob/read", baseUrlFromRequest(req));
  url.searchParams.set("path", trimmed);
  url.searchParams.set("exp", String(expiresAt));
  url.searchParams.set("sig", sig);
  return url.toString();
}

function constantTimeHexEquals(a, b) {
  const left = Buffer.from(String(a || ""), "utf8");
  const right = Buffer.from(String(b || ""), "utf8");
  if (left.length !== right.length) return false;
  return crypto.timingSafeEqual(left, right);
}

function verifySignedBlobRead(pathname, expiresAt, signature) {
  const trimmed = String(pathname || "").trim();
  const exp = Number.parseInt(String(expiresAt || ""), 10);
  if (!trimmed || !Number.isFinite(exp)) return { ok: false, code: "INVALID_BLOB_PROXY" };
  if (exp < Math.floor(Date.now() / 1000)) return { ok: false, code: "BLOB_PROXY_EXPIRED" };
  const expected = signBlobPath(trimmed, exp);
  if (!constantTimeHexEquals(signature, expected)) {
    return { ok: false, code: "INVALID_BLOB_PROXY_SIGNATURE" };
  }
  return { ok: true, pathname: trimmed };
}

module.exports = {
  createSignedBlobReadUrl,
  verifySignedBlobRead
};
