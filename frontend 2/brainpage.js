/**
 * Brainpage: standalone B−A cortical viewer (mock vertex_delta + real mesh/atlas from /api/*).
 */
function mockActivation(profile) {
  const out = new Float32Array(20484);
  for (let i = 0; i < out.length; i += 1) {
    const hemi = i < 10242 ? 0 : 1;
    const local = hemi === 0 ? i : i - 10242;
    const t = local / 10242;
    const waveA = 0.07 * Math.sin(t * 44 + (profile === "b" ? 1.1 : 0.1));
    const waveB = 0.04 * Math.cos(t * 19 + (hemi === 0 ? 0.9 : 2.2));
    const ridge = Math.exp(-((t - 0.54) ** 2) / (profile === "b" ? 0.012 : 0.022));
    const pocket = Math.exp(-((t - (hemi === 0 ? 0.32 : 0.67)) ** 2) / 0.008);
    const bias =
      profile === "b"
        ? hemi === 0
          ? 0.2 + ridge * 0.24 + pocket * 0.06
          : 0.18 + ridge * 0.31
        : hemi === 0
          ? 0.12 + ridge * 0.1
          : 0.15 + ridge * 0.16 + pocket * 0.05;
    out[i] = waveA + waveB + bias;
  }
  return out;
}

function mockVertexDeltaBminusA() {
  const a = mockActivation("a");
  const b = mockActivation("b");
  const delta = new Float32Array(20484);
  for (let i = 0; i < 20484; i += 1) delta[i] = b[i] - a[i];
  return delta;
}

async function main() {
  const host = document.getElementById("brainHost");
  const tooltip = document.getElementById("brainTooltip");
  const status = document.getElementById("brainpageStatus");
  if (!host || !status) return;

  status.textContent = "Loading mesh and atlas…";

  try {
    const mod = await import("./brain3d.js");
    const delta = mockVertexDeltaBminusA();
    const [mesh, atlas] = await Promise.all([mod.fetchBrainMesh(), mod.fetchVertexAtlas()]);
    mod.disposeBrainViewer();
    mod.mountBrainViewer(host, delta, mesh, atlas, tooltip, {});
    status.textContent = "Mock B−A data · mesh + atlas from API";
  } catch (err) {
    console.error(err);
    status.textContent =
      "Could not load /api/brain-mesh or /api/vertex-atlas. Start the app (./scripts/run_api.sh) and open this page from the same origin.";
  }
}

main();
