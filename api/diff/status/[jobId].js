const { methodNotAllowed, badRequest, serverError } = require("../../lib/http");
const { getJobStatus } = require("../../lib/runpod");
const { redis } = require("../../lib/security");
const { maybeDeleteBlobsForJob, getJobMetadata } = require("../../lib/jobs");

function filenameFromUrl(value) {
  try {
    const pathname = new URL(value).pathname;
    return decodeURIComponent(pathname.split("/").filter(Boolean).pop() || "");
  } catch (_) {
    return "";
  }
}

// Codex's `media_name_a/b` job-meta merge — preserved verbatim so the result
// page always sees the upload filename even if the worker's own meta omits it.
function resultWithJobMetadata(result, jobMeta) {
  if (!result || typeof result !== "object" || !jobMeta) return result;
  const merged = { ...result };
  const meta = { ...(result.meta || {}) };
  const modality = jobMeta.modality || (jobMeta.type === "media" ? "media" : "");
  if (modality && !meta.modality) meta.modality = modality;
  if (!meta.media_name_a) meta.media_name_a = jobMeta.mediaNameA || filenameFromUrl(jobMeta.blobUrlA);
  if (!meta.media_name_b) meta.media_name_b = jobMeta.mediaNameB || filenameFromUrl(jobMeta.blobUrlB);
  merged.meta = meta;
  return merged;
}

// Real progress events: the RunPod worker pushes JSON-encoded `(ts, status,
// message)` objects to `events:{jobId}` via Upstash Redis. We read the full
// list on each poll and surface it to the frontend, which is responsible for
// dedupe (it already keys log lines by ts+message). No synthesised events.
async function readProgressEvents(jobId) {
  try {
    const store = redis();
    const raw = await store.lrange(`events:${jobId}`, 0, -1);
    if (!Array.isArray(raw) || raw.length === 0) return [];
    const out = [];
    for (const item of raw) {
      // Upstash REST may return parsed objects (when value-as-JSON is detected)
      // or raw strings. Handle both shapes without throwing on malformed entries.
      if (item && typeof item === "object") {
        out.push(item);
        continue;
      }
      if (typeof item === "string") {
        try {
          out.push(JSON.parse(item));
        } catch (_) {
          // Drop unparseable entries silently — better than blowing up the poll.
        }
      }
    }
    return out;
  } catch (_) {
    return [];
  }
}

function explainFailure(code, message, rawStatus) {
  const normalizedCode = String(code || "RUNPOD_JOB_FAILED");
  const raw = String(rawStatus || "");
  const msg = String(message || "");
  const text = `${normalizedCode} ${raw} ${msg}`.toLowerCase();
  let reason = "RunPod reported that the job failed, but did not return a specific BrainDiff error.";
  let action = "Open the RunPod job logs for the exact stack trace. If the worker returns that error, BrainDiff will show it here.";
  if (text.includes("timeout") || text.includes("timed_out")) {
    reason = "The job took too long and was stopped.";
    action = "Try shorter files/text, then check whether the RunPod worker has enough GPU time for media jobs.";
  } else if (text.includes("media_duration_mismatch") || (text.includes("durations differ") && text.includes("within 5s"))) {
    reason = "The two files are too different in length.";
    action = "Upload files within 5 seconds of each other, or choose the trim option so BrainDiff compares the first part of both files.";
  } else if ((text.includes("cuda") && text.includes("memory")) || text.includes("out of memory") || text.includes("oom")) {
    reason = "The worker ran out of GPU memory.";
    action = "Use shorter media or a worker with more available GPU memory, then retry.";
  } else if (text.includes("hf_auth") || text.includes("hugging face") || text.includes("401") || text.includes("403")) {
    reason = "The worker could not access a required model.";
    action = "Check the Hugging Face token on the RunPod worker and confirm it has access to the gated model.";
  } else if (text.includes("ffmpeg")) {
    reason = "The worker could not read or convert the uploaded media.";
    action = "Verify ffmpeg exists in the worker image and retry with a standard mp3/wav/mp4 file.";
  } else if (text.includes("whisperx") || text.includes("transcrib")) {
    reason = "Audio transcription/alignment failed.";
    action = "Try clearer or shorter audio, and check WhisperX device/compute settings on the worker.";
  } else if (text.includes("blob") || text.includes("media_url") || text.includes("download") || text.includes("fetch")) {
    reason = "The worker could not download one of the uploaded files.";
    action = "Check the Vercel Blob token, file URL expiry, and whether both uploads are reachable from RunPod.";
  } else if (text.includes("duration") || text.includes("input_rejected")) {
    reason = "The two inputs were rejected before analysis.";
    action = "Use two files/texts that are similar enough in length and format to compare fairly.";
  } else if (text.includes("atlas")) {
    reason = "The worker is missing required brain atlas files.";
    action = "Verify the atlas files exist in the worker image under the configured atlas directory.";
  }
  return {
    code: normalizedCode,
    reason,
    action,
    raw_status: raw,
    raw_message: msg
  };
}

function mapRunpodStatus(data, jobId, jobMeta, events) {
  const raw = String(data.status || "").toUpperCase();

  if (raw === "COMPLETED") {
    return {
      status: "done",
      job_id: jobId,
      events,
      result: resultWithJobMetadata(data.output || data, jobMeta)
    };
  }

  if (raw === "FAILED" || raw === "CANCELLED" || raw === "TIMED_OUT") {
    const message =
      data.error ||
      (data.output && (data.output.error_message || data.output.error)) ||
      `Runpod status: ${raw}`;
    const code =
      (data.output && (data.output.error_code || data.output.code)) ||
      (raw === "TIMED_OUT" ? "DIFF_TIMEOUT" : "RUNPOD_JOB_FAILED");
    return {
      status: "error",
      events,
      error: {
        code,
        message,
        plain: explainFailure(code, message, raw),
        runpod_status: raw
      }
    };
  }

  // While the worker is in flight, derive the canonical status from the most
  // recent event the worker actually emitted. If the queue hasn't picked up
  // the job yet (no events at all), report "queued"; if RunPod says
  // IN_PROGRESS but we have no events, the worker is booting — report
  // "worker_booting" rather than pretending Step 1 is running.
  const last = events.length ? events[events.length - 1] : null;
  let status = last && typeof last.status === "string" ? last.status : null;
  if (!status) {
    status = raw === "IN_PROGRESS" ? "worker_booting" : "queued";
  }
  return {
    status,
    events
  };
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  const jobId = req.query.jobId;
  if (!jobId || typeof jobId !== "string") {
    return badRequest(res, "Missing jobId");
  }
  try {
    const [data, jobMeta, events] = await Promise.all([
      getJobStatus(jobId),
      getJobMetadata(jobId).catch(() => null),
      readProgressEvents(jobId)
    ]);
    const mapped = mapRunpodStatus(data, jobId, jobMeta, events);
    if (mapped.status === "done") {
      // Best-effort cleanup — never block the result on Blob/Redis hiccups.
      await Promise.all([
        maybeDeleteBlobsForJob(jobId).catch(() => {}),
        redis().del(`events:${jobId}`).catch(() => {})
      ]);
    }
    return res.status(200).json(mapped);
  } catch (err) {
    return serverError(res, err, "DIFF_STATUS_FAILED");
  }
};
