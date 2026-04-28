const { handleUpload } = require("@vercel/blob/client");
const { methodNotAllowed, serverError } = require("../lib/http");

function sanitizePathname(pathname) {
  const raw = String(pathname || "").trim();
  const cleaned = raw
    .replace(/\\/g, "/")
    .split("/")
    .filter(Boolean)
    .map((part) =>
      part
        .normalize("NFKD")
        .replace(/[^\w.\-]+/g, "-")
        .replace(/-+/g, "-")
        .replace(/^-+|-+$/g, "")
        .toLowerCase()
    )
    .filter(Boolean)
    .join("/");
  return cleaned || `uploads/brain-diff-media-${Date.now()}.bin`;
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") return methodNotAllowed(res, ["POST"]);
  try {
    const jsonResponse = await handleUpload({
      body: req.body,
      request: req,
      onBeforeGenerateToken: async (pathname) => ({
        allowedContentTypes: [
          "audio/mpeg",
          "audio/mp4",
          "audio/wav",
          "audio/flac",
          "audio/ogg",
          "video/mp4",
          "video/quicktime",
          "video/webm"
        ],
        maximumSizeInBytes: 200 * 1024 * 1024,
        addRandomSuffix: true,
        pathname: sanitizePathname(pathname)
      }),
      onUploadCompleted: async () => {}
    });
    res.status(200).json(jsonResponse);
  } catch (err) {
    serverError(res, err, "BLOB_UPLOAD_TOKEN_FAILED");
  }
};
