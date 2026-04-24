const { del } = require("@vercel/blob");
const { redis } = require("./security");
const { runtimeConfig } = require("./config");

function jobKey(jobId) {
  return `jobmeta:${jobId}`;
}

async function saveJobMetadata(jobId, metadata) {
  const cfg = runtimeConfig();
  const store = redis();
  const key = jobKey(jobId);
  await store.set(key, metadata);
  await store.expire(key, cfg.blobDeleteAfterSeconds);
}

async function getJobMetadata(jobId) {
  const store = redis();
  return store.get(jobKey(jobId));
}

async function markBlobDeleted(jobId) {
  const store = redis();
  const key = jobKey(jobId);
  const current = (await store.get(key)) || {};
  current.blobDeleted = true;
  await store.set(key, current);
}

async function maybeDeleteBlobsForJob(jobId) {
  const meta = await getJobMetadata(jobId);
  if (!meta) return false;
  const urls = [meta.blobUrlA, meta.blobUrlB].filter(Boolean);
  if (!urls.length || meta.blobDeleted) return false;
  await Promise.all(urls.map((u) => del(u)));
  await markBlobDeleted(jobId);
  return true;
}

module.exports = {
  saveJobMetadata,
  getJobMetadata,
  maybeDeleteBlobsForJob
};
