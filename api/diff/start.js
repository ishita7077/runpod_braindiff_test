const { methodNotAllowed, badRequest, serverError, readIp, jsonOrEmpty } = require("../lib/http");
const { verifyTurnstile, applyRateLimit } = require("../lib/security");
const { submitJob } = require("../lib/runpod");
const { saveJobMetadata } = require("../lib/jobs");
const { runtimeConfig } = require("../lib/config");
const { createSignedBlobReadUrl } = require("../lib/blob-proxy");

function normalizeInput(body) {
  const payload = jsonOrEmpty(body);
  const modality = String(payload.modality || "text").toLowerCase();
  return {
    modality,
    textA: typeof payload.text_a === "string" ? payload.text_a.trim() : "",
    textB: typeof payload.text_b === "string" ? payload.text_b.trim() : "",
    mediaUrlA: typeof payload.media_url_a === "string" ? payload.media_url_a.trim() : "",
    mediaUrlB: typeof payload.media_url_b === "string" ? payload.media_url_b.trim() : "",
    mediaPathA: typeof payload.media_path_a === "string" ? payload.media_path_a.trim() : "",
    mediaPathB: typeof payload.media_path_b === "string" ? payload.media_path_b.trim() : "",
    turnstileToken: payload.turnstileToken || payload.turnstile_token || ""
  };
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") return methodNotAllowed(res, ["POST"]);
  try {
    const ip = readIp(req);
    const input = normalizeInput(req.body);
    const cfg = runtimeConfig();
    if (cfg.turnstileEnabled && !String(input.turnstileToken || "").trim()) {
      return badRequest(res, "Missing bot protection token", "TURNSTILE_MISSING");
    }
    if (input.modality === "text" && (!input.textA || !input.textB)) {
      return badRequest(res, "Both text_a and text_b are required for text jobs");
    }
    const hasMediaRefs = (input.mediaPathA && input.mediaPathB) || (input.mediaUrlA && input.mediaUrlB);
    if ((input.modality === "audio" || input.modality === "video") && !hasMediaRefs) {
      return badRequest(
        res,
        "media_path_a and media_path_b are required for audio/video jobs"
      );
    }

    const rateType = input.modality === "text" ? "text" : "media";
    const [captcha, limit] = await Promise.all([
      verifyTurnstile({ token: input.turnstileToken, ip }),
      applyRateLimit({ ip, type: rateType })
    ]);
    if (!captcha.ok) {
      return res.status(403).json({
        code: captcha.code,
        message: "Bot verification failed"
      });
    }
    if (!limit.ok) {
      return res.status(429).json({
        code: limit.code,
        message: "Rate limit exceeded",
        limit: limit.limit
      });
    }

    const mediaUrlA = input.mediaPathA ? createSignedBlobReadUrl(req, input.mediaPathA) : input.mediaUrlA || undefined;
    const mediaUrlB = input.mediaPathB ? createSignedBlobReadUrl(req, input.mediaPathB) : input.mediaUrlB || undefined;
    const runpodInput = {
      mode: input.modality,
      text_a: input.textA || undefined,
      text_b: input.textB || undefined,
      media_url_a: mediaUrlA,
      media_url_b: mediaUrlB
    };
    const submitted = await submitJob(runpodInput);
    const jobId = submitted.id || submitted.jobId;
    if (!jobId) {
      throw new Error("Runpod response missing job id");
    }

    await saveJobMetadata(jobId, {
      createdAt: new Date().toISOString(),
      ip,
      type: rateType,
      blobUrlA: input.mediaPathA || input.mediaUrlA || null,
      blobUrlB: input.mediaPathB || input.mediaUrlB || null,
      blobDeleted: false
    });

    return res.status(200).json({
      job_id: jobId,
      request_id: jobId,
      status: "queued"
    });
  } catch (err) {
    return serverError(res, err, "DIFF_START_FAILED");
  }
};
