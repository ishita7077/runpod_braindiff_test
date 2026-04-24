const { methodNotAllowed, badRequest, serverError } = require("../../lib/http");
const { getJobStatus } = require("../../lib/runpod");
const { maybeDeleteBlobsForJob } = require("../../lib/jobs");

function mapRunpodStatus(data, jobId) {
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
  return {
    status: data.status ? String(data.status).toLowerCase() : "running",
    phase: data.executionTime ? "running" : "queued",
    progress: 0.5
  };
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  const jobId = req.query.jobId;
  if (!jobId || typeof jobId !== "string") {
    return badRequest(res, "Missing jobId");
  }
  try {
    const data = await getJobStatus(jobId);
    const mapped = mapRunpodStatus(data, jobId);
    if (mapped.status === "done") {
      await maybeDeleteBlobsForJob(jobId);
    }
    return res.status(200).json(mapped);
  } catch (err) {
    return serverError(res, err, "DIFF_STATUS_FAILED");
  }
};
