const { methodNotAllowed, badRequest, serverError } = require("../../lib/http");
const { getJobStatus } = require("../../lib/runpod");
const { redis } = require("../../lib/security");
const { maybeDeleteBlobsForJob, getJobMetadata } = require("../../lib/jobs");

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

function mapRunpodStatus(data, jobId, events) {
  const raw = String(data.status || "").toUpperCase();

  if (raw === "COMPLETED") {
    return {
      status: "done",
      job_id: jobId,
      events,
      result: data.output || data
    };
  }

  if (raw === "FAILED" || raw === "CANCELLED" || raw === "TIMED_OUT") {
    return {
      status: "error",
      events,
      error: {
        code: "RUNPOD_JOB_FAILED",
        message: data.error || `Runpod status: ${raw}`
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
    const [data, events] = await Promise.all([
      getJobStatus(jobId),
      readProgressEvents(jobId)
    ]);
    const mapped = mapRunpodStatus(data, jobId, events);
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
