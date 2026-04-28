#!/usr/bin/env node
/**
 * Mirrors Runpod Serverless "Requests" payloads from TESTING.md.
 * Usage:
 *   RUNPOD_API_KEY=... RUNPOD_ENDPOINT_ID=... node scripts/runpod-smoke.mjs
 * Optional (public HTTPS URLs the worker can GET):
 *   RUNPOD_SMOKE_AUDIO_URL_A=... RUNPOD_SMOKE_AUDIO_URL_B=...
 *   RUNPOD_SMOKE_VIDEO_URL_A=... RUNPOD_SMOKE_VIDEO_URL_B=...
 * Or pass once: node scripts/runpod-smoke.mjs --audio-a URL --audio-b URL
 *
 * Exit: 0 success, 1 failure, 2 missing env (nothing run)
 */

import process from "node:process";

const key = process.env.RUNPOD_API_KEY;
const endpointId = process.env.RUNPOD_ENDPOINT_ID;
if (!key || !endpointId) {
  console.error(
    "Missing RUNPOD_API_KEY or RUNPOD_ENDPOINT_ID. Set both, then re-run."
  );
  process.exit(2);
}

const base = `https://api.runpod.ai/v2/${endpointId}`;

function parseArgs(argv) {
  const out = {};
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--audio-a") out.audioA = argv[++i];
    else if (a === "--audio-b") out.audioB = argv[++i];
    else if (a === "--video-a") out.videoA = argv[++i];
    else if (a === "--video-b") out.videoB = argv[++i];
  }
  return out;
}

async function submit(input) {
  const res = await fetch(`${base}/run`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${key}`
    },
    body: JSON.stringify({ input })
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(`submit ${res.status}: ${JSON.stringify(data)}`);
  }
  const jobId = data.id;
  if (!jobId) throw new Error(`no job id: ${JSON.stringify(data)}`);
  return jobId;
}

async function poll(jobId) {
  const deadline = Date.now() + 15 * 60 * 1000;
  while (Date.now() < deadline) {
    const res = await fetch(`${base}/status/${jobId}`, {
      headers: { authorization: `Bearer ${key}` }
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(`status ${res.status}: ${JSON.stringify(data)}`);
    }
    const st = data.status;
    if (st === "COMPLETED") return data;
    if (st === "FAILED" || st === "CANCELLED") {
      throw new Error(`job ${st}: ${JSON.stringify(data)}`);
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error("timeout waiting for job");
}

async function runCase(name, input) {
  process.stdout.write(`\n== ${name} ==\n`);
  const id = await submit(input);
  process.stdout.write(`job ${id}\n`);
  const result = await poll(id);
  process.stdout.write(`${name} OK\n`);
  return result;
}

const cli = parseArgs(process.argv);

async function main() {
  await runCase("text", {
    mode: "text",
    text_a:
      "AI policy should focus on transparency, safety, and measured rollout.",
    text_b:
      "AI policy must move fast to preserve innovation while managing risk."
  });

  const audioA =
    cli.audioA || process.env.RUNPOD_SMOKE_AUDIO_URL_A || "";
  const audioB =
    cli.audioB || process.env.RUNPOD_SMOKE_AUDIO_URL_B || "";
  if (audioA && audioB) {
    await runCase("audio", {
      mode: "audio",
      media_url_a: audioA,
      media_url_b: audioB
    });
  } else {
    process.stdout.write(
      "\n== audio (skipped) ==\nSet RUNPOD_SMOKE_AUDIO_URL_A/B or --audio-a/--audio-b with public URLs.\n"
    );
  }

  const videoA =
    cli.videoA || process.env.RUNPOD_SMOKE_VIDEO_URL_A || "";
  const videoB =
    cli.videoB || process.env.RUNPOD_SMOKE_VIDEO_URL_B || "";
  if (videoA && videoB) {
    await runCase("video", {
      mode: "video",
      media_url_a: videoA,
      media_url_b: videoB
    });
  } else {
    process.stdout.write(
      "\n== video (skipped) ==\nSet RUNPOD_SMOKE_VIDEO_URL_A/B or --video-a/--video-b with public URLs.\n"
    );
  }
}

main().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
