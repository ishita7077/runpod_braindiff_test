const { handleUpload } = require("@vercel/blob/client");
const { methodNotAllowed, serverError } = require("../lib/http");

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
        pathname: pathname || "braindiff-media"
      }),
      onUploadCompleted: async () => {}
    });
    res.status(200).json(jsonResponse);
  } catch (err) {
    serverError(res, err, "BLOB_UPLOAD_TOKEN_FAILED");
  }
};
