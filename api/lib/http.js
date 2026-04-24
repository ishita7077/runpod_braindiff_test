function readIp(req) {
  const forwarded = req.headers["x-forwarded-for"];
  if (typeof forwarded === "string" && forwarded.trim()) {
    return forwarded.split(",")[0].trim();
  }
  const realIp = req.headers["x-real-ip"];
  if (typeof realIp === "string" && realIp.trim()) {
    return realIp.trim();
  }
  return "0.0.0.0";
}

function methodNotAllowed(res, allowed) {
  res.setHeader("Allow", allowed.join(", "));
  res.status(405).json({ code: "METHOD_NOT_ALLOWED", message: "Method not allowed" });
}

function badRequest(res, message, code = "BAD_REQUEST") {
  res.status(400).json({ code, message });
}

function serverError(res, err, fallbackCode = "INTERNAL_ERROR") {
  const message = err instanceof Error ? err.message : "Unexpected server error";
  res.status(500).json({ code: fallbackCode, message });
}

function jsonOrEmpty(body) {
  if (!body || typeof body !== "object") return {};
  return body;
}

module.exports = {
  readIp,
  methodNotAllowed,
  badRequest,
  serverError,
  jsonOrEmpty
};
