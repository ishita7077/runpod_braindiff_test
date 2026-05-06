const { methodNotAllowed, badRequest, serverError, readIp, jsonOrEmpty } = require("../lib/http");
const { verifyTurnstile, applyRateLimit } = require("../lib/security");
const { submitJob } = require("../lib/runpod");
const { saveJobMetadata } = require("../lib/jobs");
const { runtimeConfig } = require("../lib/config");

function normalizeInput(body) {
  const payload = jsonOrEmpty(body);
  const modality = String(payload.modality || "text").toLowerCase();
  // Display names: short, human-readable labels for each input. Auto-suggested
  // on the launch page (extracted from text or filename) and editable by the
  // user. Capped at 60 chars defensively. Stored in job metadata and forwarded
  // to the worker so the entire UI uses the same labels everywhere.
  const cap = (s, n) => (typeof s === "string" ? s.trim().slice(0, n) : "");
  return {
    modality,
    textA: typeof payload.text_a === "string" ? payload.text_a.trim() : "",
    textB: typeof payload.text_b === "string" ? payload.text_b.trim() : "",
    mediaUrlA: typeof payload.media_url_a === "string" ? payload.media_url_a.trim() : "",
    mediaUrlB: typeof payload.media_url_b === "string" ? payload.media_url_b.trim() : "",
    mediaNameA: typeof payload.media_name_a === "string" ? payload.media_name_a.trim() : "",
    mediaNameB: typeof payload.media_name_b === "string" ? payload.media_name_b.trim() : "",
    mediaDurationA: Number.isFinite(Number(payload.media_duration_a_s)) ? Number(payload.media_duration_a_s) : null,
    mediaDurationB: Number.isFinite(Number(payload.media_duration_b_s)) ? Number(payload.media_duration_b_s) : null,
    displayNameA: cap(payload.display_name_a, 60),
    displayNameB: cap(payload.display_name_b, 60),
    trimToShorter: payload.trim_to_shorter === true,
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
    if ((input.modality === "audio" || input.modality === "video") && (!input.mediaUrlA || !input.mediaUrlB)) {
      return badRequest(
        res,
        "media_url_a and media_url_b are required for audio/video jobs"
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

    const runpodInput = {
      mode: input.modality,
      text_a: input.textA || undefined,
      text_b: input.textB || undefined,
      media_url_a: input.mediaUrlA || undefined,
      media_url_b: input.mediaUrlB || undefined,
      display_name_a: input.displayNameA || undefined,
      display_name_b: input.displayNameB || undefined,
      trim_to_shorter: input.trimToShorter || undefined,
      blob_token: input.modality === "audio" || input.modality === "video" ? cfg.blobReadWriteToken : undefined
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
      modality: input.modality,
      mediaNameA: input.mediaNameA || null,
      mediaNameB: input.mediaNameB || null,
      displayNameA: input.displayNameA || null,
      displayNameB: input.displayNameB || null,
      mediaDurationA: input.mediaDurationA,
      mediaDurationB: input.mediaDurationB,
      trimToShorter: input.trimToShorter,
      blobUrlA: input.mediaUrlA || null,
      blobUrlB: input.mediaUrlB || null,
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
