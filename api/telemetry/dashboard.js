const { methodNotAllowed } = require("../lib/http");

const DASHBOARD_URL =
  process.env.TELEMETRY_DASHBOARD_URL ||
  process.env.BRAIN_DIFF_BACKEND_TELEMETRY_DASHBOARD_URL ||
  "";

const EMPTY_DASHBOARD = {
  runs: [],
  aggregate: {}
};

async function fetchRemoteDashboard(limit, offset) {
  if (!DASHBOARD_URL) return null;
  const url = new URL(DASHBOARD_URL);
  if (!url.searchParams.has("limit")) url.searchParams.set("limit", String(limit));
  if (!url.searchParams.has("offset")) url.searchParams.set("offset", String(offset));
  const res = await fetch(url.toString(), { method: "GET" });
  if (!res.ok) return null;
  const payload = await res.json();
  if (!payload || typeof payload !== "object") return null;
  return {
    runs: Array.isArray(payload.runs) ? payload.runs : [],
    aggregate: payload.aggregate && typeof payload.aggregate === "object" ? payload.aggregate : {}
  };
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  const limit = Number.parseInt(String(req.query.limit || "1000"), 10) || 1000;
  const offset = Number.parseInt(String(req.query.offset || "0"), 10) || 0;
  res.setHeader("Cache-Control", "public, max-age=15, s-maxage=15");
  try {
    const data = await fetchRemoteDashboard(limit, offset);
    return res.status(200).json(data || EMPTY_DASHBOARD);
  } catch (_err) {
    return res.status(200).json(EMPTY_DASHBOARD);
  }
};
