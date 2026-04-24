const { runtimeConfig } = require("./config");

function endpoints() {
  const cfg = runtimeConfig();
  const base = `https://api.runpod.ai/v2/${cfg.runpodEndpointId}`;
  return {
    run: `${base}/run`,
    status: (jobId) => `${base}/status/${jobId}`
  };
}

async function submitJob(input) {
  const cfg = runtimeConfig();
  const url = endpoints().run;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${cfg.runpodApiKey}`
    },
    body: JSON.stringify({ input })
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(`Runpod submit failed: ${res.status} ${JSON.stringify(data)}`);
  }
  return data;
}

async function getJobStatus(jobId) {
  const cfg = runtimeConfig();
  const url = endpoints().status(jobId);
  const res = await fetch(url, {
    headers: { authorization: `Bearer ${cfg.runpodApiKey}` }
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(`Runpod status failed: ${res.status} ${JSON.stringify(data)}`);
  }
  return data;
}

module.exports = {
  submitJob,
  getJobStatus
};
