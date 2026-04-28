const { methodNotAllowed, badRequest, serverError } = require("../../lib/http");
const { getJobStatus } = require("../../lib/runpod");
const { maybeDeleteBlobsForJob, getJobMetadata } = require("../../lib/jobs");

function mapRunpodStatus(data, jobId, jobMeta) {
  const raw = String(data.status || "").toUpperCase();

  if (raw === "COMPLETED") {
    return {
      status: "done",
      job_id: jobId,
      result: data.output || data
    };
  }

  if (raw === "FAILED" || raw === "CANCELLED" || raw === "TIMED_OUT") {
    return {
      status: "error",
      error: {
        code: "RUNPOD_JOB_FAILED",
        message: data.error || `Runpod status: ${raw}`
      }
    };
  }

  // Both IN_QUEUE (waiting for a worker) and IN_PROGRESS (worker executing)
  // map to "queued" so the frontend's STATUS_TO_STEP / applyStatus /
  // DS_STEPS[0].backend keep step 0 active throughout. Without RunPod
  // intermediate events we can't surface finer-grained progress.
  const rawLower = data.status ? String(data.status).toLowerCase() : "running";
  const normalized =
    rawLower === "in_queue" || rawLower === "in_progress" ? "queued" : rawLower;

  // Synthesize a single "queued" event using the job's creation timestamp
  // (stored in Redis by /api/diff/start). DS.update() uses this to start the
  // elapsed clock and log one "job accepted" entry. appendLog() deduplicates
  // by (ts::msg), so re-polling every 1.5 s never floods the log.
  const createdAt = jobMeta && jobMeta.createdAt;
  const events = createdAt
    ? [{ status: "queued", timestamp: createdAt, message: "job accepted" }]
    : [];

  return {
    status: normalized,
    phase: data.executionTime ? "running" : "queued",
    progress: 0.5,
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
    // Fetch RunPod status and Redis job metadata in parallel.
    // getJobMetadata failure (e.g. missing Redis env var) is non-fatal —
    // the response still returns a valid status without the clock event.
    const [data, jobMeta] = await Promise.all([
      getJobStatus(jobId),
      getJobMetadata(jobId).catch(() => null)
    ]);
    const mapped = mapRunpodStatus(data, jobId, jobMeta);
    if (mapped.status === "done") {
      // Blob cleanup is best-effort — a Redis/Blob failure must not prevent
      // the result payload from reaching the results page.
      await maybeDeleteBlobsForJob(jobId).catch(() => {});
    }
    return res.status(200).json(mapped);
  } catch (err) {
    return serverError(res, err, "DIFF_STATUS_FAILED");
  }
};
