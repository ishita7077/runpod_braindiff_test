const { Readable } = require("stream");
const { get } = require("@vercel/blob");
const { methodNotAllowed, badRequest, serverError } = require("../lib/http");
const { verifySignedBlobRead } = require("../lib/blob-proxy");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  try {
    const parsedUrl = new URL(req.url, "http://localhost");
    const verdict = verifySignedBlobRead(
      parsedUrl.searchParams.get("path"),
      parsedUrl.searchParams.get("exp"),
      parsedUrl.searchParams.get("sig")
    );
    if (!verdict.ok) {
      return badRequest(res, "Invalid blob download link", verdict.code);
    }

    const blob = await get(verdict.pathname, {
      access: "private"
    });
    if (!blob) {
      return res.status(404).json({ code: "BLOB_NOT_FOUND", message: "Blob not found" });
    }
    if (blob.statusCode !== 200 || !blob.stream) {
      return res.status(502).json({ code: "BLOB_FETCH_FAILED", message: "Could not read private blob" });
    }

    res.setHeader("Cache-Control", "private, no-store");
    if (blob.blob.contentType) res.setHeader("Content-Type", blob.blob.contentType);
    if (blob.blob.contentDisposition) res.setHeader("Content-Disposition", blob.blob.contentDisposition);
    if (blob.blob.size != null) res.setHeader("Content-Length", String(blob.blob.size));
    Readable.fromWeb(blob.stream).pipe(res);
  } catch (err) {
    return serverError(res, err, "BLOB_READ_FAILED");
  }
};
