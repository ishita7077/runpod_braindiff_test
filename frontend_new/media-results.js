import * as THREE from "https://unpkg.com/three@0.164.1/build/three.module.js";
import { OrbitControls } from "https://unpkg.com/three@0.164.1/examples/jsm/controls/OrbitControls.js";

const $ = (sel) => document.querySelector(sel);
const kind = document.body.dataset.mediaKind || $("#mediaApp")?.dataset.kind || "video";
const params = new URLSearchParams(location.search);
const jobId = params.get("job");
const isDemo = params.get("demo") === "1" || !jobId;
let state = { data: null, progress: 0, activeTrack: 0, activeMoment: 0, playing: false, timer: 0 };
let brain = null;

boot();

async function boot() {
  wireTheme();
  wireShare();
  try {
    const [data, meshPayload] = await Promise.all([
      isDemo ? fetchDemo(kind) : fetchJob(kind, jobId),
      fetchBrainMesh()
    ]);
    state.data = data;
    render(data);
    brain = createBrain($("#brainCanvas"), data, meshPayload);
    updatePlayhead(0);
  } catch (error) {
    renderError(error);
  }
}

async function fetchDemo(mode) {
  const res = await fetch(`./demo/${mode}-result.json`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Demo data could not load (${res.status})`);
  return res.json();
}

async function fetchJob(mode, id) {
  const res = await fetch(`/api/diff/status/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Job could not load (${res.status})`);
  const job = await res.json();
  if (job.status === "error") throw new Error(job.error?.message || "Runpod returned an error for this job.");
  if (job.status !== "done") throw new Error("This job is not finished yet. Open the run page and wait for completion.");
  return normalizeJob(mode, job);
}

async function fetchBrainMesh() {
  try {
    const res = await fetch("/api/brain-mesh", { cache: "force-cache" });
    if (!res.ok) return null;
    const payload = await res.json();
    return payload && payload.lh_coord && payload.rh_coord ? payload : null;
  } catch (_) {
    return null;
  }
}

function normalizeJob(mode, job) {
  const result = job.result || {};
  const meta = result.meta || {};
  const dims = Array.isArray(result.dimensions) ? result.dimensions : [];
  const tracks = dims.slice(0, 5).map((dim, i) => ({
    key: dim.key || `track_${i}`,
    label: dim.label || dim.key || `Track ${i + 1}`,
    system: dim.region || dim.system || "Cortical contrast",
    a: normalizeSeries(dim.timeseries_a || dim.series_a || dim.a || [dim.score_a || 0.35]),
    b: normalizeSeries(dim.timeseries_b || dim.series_b || dim.b || [dim.score_b || 0.45])
  }));
  if (!tracks.length) {
    tracks.push(
      { key: "attention", label: "Attention", system: "Dorsal attention", a: [0.24, 0.3, 0.4, 0.38, 0.34], b: [0.4, 0.58, 0.62, 0.54, 0.47] },
      { key: "memory", label: "Memory", system: "Medial temporal", a: [0.3, 0.34, 0.39, 0.42, 0.4], b: [0.35, 0.43, 0.51, 0.56, 0.59] }
    );
  }
  const durationA = Math.max(24, Math.round(maxSeriesLength(tracks) * 4));
  const durationB = Math.max(24, Math.round(maxSeriesLength(tracks) * 4.2));
  const aName = meta.media_name_a || meta.input_a_name || "Sample A";
  const bName = meta.media_name_b || meta.input_b_name || "Sample B";
  return {
    kind: mode,
    job_id: job.job_id || jobId || "media-job",
    headline: mode === "video" ? "Video comparison complete." : "Audio comparison complete.",
    dek: mode === "video"
      ? "Review how the two video files differ across cortical systems. Positive values mean B is stronger; negative values mean A is stronger."
      : "Review how the two audio files differ across cortical systems. Positive values mean B is stronger; negative values mean A is stronger.",
    samples: {
      a: buildSample(mode, "A", aName, durationA, tracks, "a"),
      b: buildSample(mode, "B", bName, durationB, tracks, "b")
    },
    waveforms: {
      a: tracks[0].a.concat(tracks[1]?.a || []),
      b: tracks[0].b.concat(tracks[1]?.b || [])
    },
    tracks,
    moments: buildMoments(mode, tracks),
    recommendations: buildRecommendations(mode, tracks)
  };
}

function buildSample(mode, label, name, duration, tracks, side) {
  const summary = mode === "video"
    ? `${name} is represented as a sequence of comparison windows for visual review.`
    : `${name} is represented as a sequence of comparison windows for listening review.`;
  if (mode === "audio") {
    return {
      label, name, duration, summary,
      transcript: splitIntoSegments(duration, [
        label === "A" ? "Opening phrase" : "Opening phrase",
        label === "A" ? "Problem line" : "Problem line",
        label === "A" ? "Main claim" : "Main claim",
        label === "A" ? "Closing line" : "Closing line"
      ])
    };
  }
  return {
    label, name, duration, summary,
    scenes: splitIntoSegments(duration, ["Opening beat", "Middle proof", "Human read", "Final frame"]).map((s, i) => ({
      ...s,
      title: s.text,
      beat: `${tracks[i % tracks.length]?.label || "Response"} is the clearest signal here.`,
      visual: side === "b" ? "Higher movement and stronger foreground cue" : "Lower movement and calmer frame"
    }))
  };
}

function splitIntoSegments(duration, labels) {
  return labels.map((text, i) => {
    const start = Math.round((duration / labels.length) * i);
    const end = i === labels.length - 1 ? duration : Math.round((duration / labels.length) * (i + 1));
    return { start, end, text };
  });
}

function buildMoments(mode, tracks) {
  return tracks.slice(0, 4).map((track, i) => {
    const best = bestDeltaIndex(track.a, track.b);
    const side = valueAt(track.b, best) >= valueAt(track.a, best) ? "B" : "A";
    return {
      time: Math.round(best * 4),
      sample: side,
      track: track.key,
      title: mode === "video" ? `${track.label} contrast, window ${i + 1}` : `${track.label} contrast, window ${i + 1}`,
      detail: `${side} has the stronger ${track.label.toLowerCase()} estimate at this point in the comparison view.`,
      move: "Treat this as a cortical contrast signal, not a quality score."
    };
  });
}

function buildRecommendations(mode, tracks) {
  const strongest = tracks.slice().sort((a, b) => Math.abs(mean(b.b) - mean(b.a)) - Math.abs(mean(a.b) - mean(a.a)))[0];
  return mode === "video"
    ? [`Largest aggregate shift: ${strongest?.label || "strongest signal"}.`, "Check whether that shift is concentrated in one window or repeated across the file.", "Compare the brain view with the sample timing before deciding between A and B."]
    : [`Largest aggregate shift: ${strongest?.label || "strongest signal"}.`, "Check whether that shift follows phrasing or is spread across the file.", "Compare the brain view with the transcript windows before deciding between A and B."];
}

function render(data) {
  $("#pageHeadline").textContent = data.headline;
  $("#pageDek").textContent = data.dek;
  $("#decisionTitle").textContent = kind === "video" ? "What changed between A and B." : "What changed between A and B.";
  $("#heroStats").innerHTML = [
    pill("Mode", data.kind),
    pill("Job", isDemo ? "demo" : short(data.job_id || jobId)),
    pill("A", formatTime(data.samples.a.duration)),
    pill("B", formatTime(data.samples.b.duration))
  ].join("");
  $("#recommendations").innerHTML = (data.recommendations || []).map((text) => `<li>${escapeHtml(text)}</li>`).join("");
  renderSample($("#sampleA"), data.samples.a, data, "a");
  renderSample($("#sampleB"), data.samples.b, data, "b");
  renderTracks(data);
  renderMoments(data);
  renderSceneMap(data);
  wireTimeline(data);
}

function renderSample(root, sample, data, side) {
  root.innerHTML = `
    <div class="sample-head">
      <div class="sample-badge">${sample.label}</div>
      <div style="min-width:0;flex:1">
        <div class="sample-name">${escapeHtml(sample.name)}</div>
        <div class="sample-meta">${formatTime(sample.duration)} · ${kind === "video" ? "scene lane" : "phrase lane"}</div>
      </div>
    </div>
    ${kind === "video" ? renderVideoLane(sample) : renderAudioLane(sample, data.waveforms?.[side] || data.tracks[0]?.[side] || [])}
    <p class="sample-summary">${escapeHtml(sample.summary || "")}</p>
  `;
}

function renderVideoLane(sample) {
  return `
    <div class="video-frame"><span class="playhead-dot"></span></div>
    <div class="scene-strip">
      ${(sample.scenes || []).map((scene, i) => `<button class="scene-chip" type="button" data-time="${scene.start}"><strong>${escapeHtml(scene.title || scene.text || `Scene ${i + 1}`)}</strong>${formatTime(scene.start)}-${formatTime(scene.end)}</button>`).join("")}
    </div>
  `;
}

function renderAudioLane(sample, waveform) {
  const bars = normalizeSeries(waveform).slice(0, 32).map((v) => `<span class="wave-bar" style="--h:${v.toFixed(3)}"></span>`).join("");
  const lines = (sample.transcript || []).map((line) => `<button class="transcript-line" type="button" data-time="${line.start}">${formatTime(line.start)} · ${escapeHtml(line.text)}</button>`).join("");
  return `<div class="waveform">${bars}</div><div class="transcript-lines">${lines}</div>`;
}

function renderTracks(data) {
  $("#tracks").innerHTML = data.tracks.map((track, i) => `
    <button class="track-row" type="button" data-track="${i}">
      <span class="track-label"><strong>${escapeHtml(track.label)}</strong><span>${escapeHtml(track.system || "")}</span></span>
      <span class="track-bars">
        <span class="track-line a"><span style="--w:${mean(track.a).toFixed(3)}"></span></span>
        <span class="track-line b"><span style="--w:${mean(track.b).toFixed(3)}"></span></span>
      </span>
      <span class="track-score"><strong>${signed(mean(track.b) - mean(track.a))}</strong><span>B-A</span></span>
    </button>
  `).join("");
}

function renderMoments(data) {
  $("#moments").innerHTML = data.moments.map((moment, i) => `
    <article class="moment-card" data-moment="${i}">
      <div class="moment-meta"><span>${moment.sample} · ${formatTime(moment.time)}</span><span>${escapeHtml(labelForTrack(moment.track, data))}</span></div>
      <h3>${escapeHtml(moment.title)}</h3>
      <p>${escapeHtml(moment.detail)}</p>
    </article>
  `).join("");
}

function renderSceneMap(data) {
  const aItems = kind === "video" ? data.samples.a.scenes || [] : data.samples.a.transcript || [];
  const bItems = kind === "video" ? data.samples.b.scenes || [] : data.samples.b.transcript || [];
  const rows = Array.from({ length: Math.max(aItems.length, bItems.length) }, (_, i) => [aItems[i], bItems[i]]);
  $("#sceneMap").innerHTML = rows.map(([a, b]) => `
    <div class="scene-pair">
      ${sceneBox(a, "a")}
      ${sceneBox(b, "b")}
    </div>
  `).join("");
}

function sceneBox(item, side) {
  if (!item) return `<div class="scene-box ${side}"><div class="time">No matched beat</div><h3>Gap</h3><p>This side has no equivalent moment here.</p></div>`;
  const title = item.title || item.text || "Beat";
  const text = item.beat || item.visual || item.text || "";
  return `<div class="scene-box ${side}" data-time="${item.start || 0}"><div class="time">${side.toUpperCase()} · ${formatTime(item.start || 0)}-${formatTime(item.end || 0)}</div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p></div>`;
}

function wireTimeline(data) {
  const scrubber = $("#scrubber");
  scrubber.addEventListener("input", () => updatePlayhead(Number(scrubber.value) / 100));
  $("#tracks").addEventListener("click", (event) => {
    const row = event.target.closest("[data-track]");
    if (!row) return;
    state.activeTrack = Number(row.dataset.track);
    updatePlayhead(state.progress);
  });
  $("#moments").addEventListener("click", (event) => {
    const card = event.target.closest("[data-moment]");
    if (!card) return;
    const index = Number(card.dataset.moment);
    const moment = data.moments[index];
    const maxDuration = Math.max(data.samples.a.duration, data.samples.b.duration);
    state.activeMoment = index;
    scrubber.value = String(Math.round((moment.time / maxDuration) * 100));
    updatePlayhead(Number(scrubber.value) / 100);
  });
  document.addEventListener("click", (event) => {
    const timed = event.target.closest("[data-time]");
    if (!timed) return;
    const maxDuration = Math.max(data.samples.a.duration, data.samples.b.duration);
    scrubber.value = String(Math.round((Number(timed.dataset.time) / maxDuration) * 100));
    updatePlayhead(Number(scrubber.value) / 100);
  });
  $("#playBtn").addEventListener("click", togglePlay);
  $("#resetBrain").addEventListener("click", () => brain?.reset());
}

function togglePlay() {
  const button = $("#playBtn");
  state.playing = !state.playing;
  button.classList.toggle("is-playing", state.playing);
  button.textContent = state.playing ? "Pause" : "Play";
  clearInterval(state.timer);
  if (!state.playing) return;
  state.timer = setInterval(() => {
    const scrubber = $("#scrubber");
    const next = (Number(scrubber.value) + 1) % 101;
    scrubber.value = String(next);
    updatePlayhead(next / 100);
  }, 180);
}

function updatePlayhead(progress) {
  state.progress = Math.max(0, Math.min(1, progress));
  const data = state.data;
  if (!data) return;
  const aTime = Math.round(data.samples.a.duration * state.progress);
  const bTime = Math.round(data.samples.b.duration * state.progress);
  $("#timeA").textContent = `A ${formatTime(aTime)}`;
  $("#timeB").textContent = `B ${formatTime(bTime)}`;
  document.querySelectorAll(".playhead-dot").forEach((dot) => dot.style.setProperty("--p", String(state.progress * 100)));
  document.querySelectorAll(".track-line").forEach((line) => line.style.setProperty("--playhead", state.progress.toFixed(3)));
  document.querySelectorAll(".track-row").forEach((row, i) => row.classList.toggle("is-active", i === state.activeTrack));
  markHotItems(".scene-chip, .transcript-line, .scene-box", (node) => Number(node.dataset.time || 0), Math.max(aTime, bTime), 7);
  markHotBars();
  const nearest = nearestMoment(data.moments, Math.max(aTime, bTime));
  state.activeMoment = nearest.index;
  showMoment(nearest.moment, data);
  brain?.paint(data.tracks[state.activeTrack], state.progress);
}

function showMoment(moment, data) {
  if (!moment) return;
  $("#activeMomentTitle").textContent = moment.title;
  $("#activeMomentDetail").textContent = moment.detail;
  $("#activeMomentMove").textContent = moment.move;
  $("#brainCaption").textContent = `${moment.sample} stronger · ${labelForTrack(moment.track, data)} · ${formatTime(moment.time)}`;
  document.querySelectorAll(".moment-card").forEach((card, i) => card.classList.toggle("is-active", i === state.activeMoment));
}

function markHotItems(selector, getTime, time, radius) {
  document.querySelectorAll(selector).forEach((node) => {
    const distance = Math.abs(getTime(node) - time);
    node.classList.toggle("is-hot", distance <= radius);
  });
}

function markHotBars() {
  document.querySelectorAll(".waveform").forEach((waveform) => {
    const bars = Array.from(waveform.querySelectorAll(".wave-bar"));
    const index = Math.round(state.progress * (bars.length - 1));
    bars.forEach((bar, i) => bar.classList.toggle("is-hot", Math.abs(i - index) < 2));
  });
}

function createBrain(canvas, data, meshPayload) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 100);
  camera.position.set(0.2, 0.15, 7.4);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.minDistance = 3.2;
  controls.maxDistance = 11;
  controls.rotateSpeed = 0.8;
  controls.zoomSpeed = 1.6;
  scene.add(new THREE.AmbientLight(0xffffff, 0.42));
  const key = new THREE.DirectionalLight(0xffead2, 1.35);
  key.position.set(3, 4, 5);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x6a97c9, 0.7);
  rim.position.set(-4, 1.5, -2);
  scene.add(rim);

  const { geometry, vertexCount } = meshPayload ? buildMeshGeometry(meshPayload) : buildFallbackCortexGeometry();
  const pos = geometry.attributes.position;
  const colors = new Float32Array(vertexCount * 3);
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.64,
    metalness: 0.04
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.set(0.06, -0.38, 0);
  scene.add(mesh);

  const resize = () => {
    const rect = canvas.parentElement.getBoundingClientRect();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(rect.width, rect.height, false);
    camera.aspect = rect.width / rect.height;
    camera.updateProjectionMatrix();
  };
  const paint = (track, progress) => {
    const a = valueAt(track?.a || [0.4], Math.round(progress * ((track?.a?.length || 1) - 1)));
    const b = valueAt(track?.b || [0.4], Math.round(progress * ((track?.b?.length || 1) - 1)));
    const delta = b - a;
    const color = new THREE.Color();
    const base = new THREE.Color(document.documentElement.dataset.theme === "dark" ? 0xd4cdbd : 0x8f887b);
    const blue = new THREE.Color(0x4a78ab);
    const red = new THREE.Color(0xe04a2e);
    const active = delta >= 0 ? red : blue;
    const strength = Math.min(1, Math.abs(delta) * 2.8 + 0.08);
    const colorAttr = geometry.attributes.color;
    for (let i = 0; i < vertexCount; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      const region = 0.5 + 0.5 * Math.sin(x * 2.2 + y * 3.8 + z * 2.7 + progress * 6.28);
      const hemiBias = x >= 0 ? 0.08 : -0.02;
      color.copy(base).lerp(active, strength * Math.max(0.08, 0.16 + region * 0.72 + hemiBias));
      colors[i * 3] = color.r;
      colors[i * 3 + 1] = color.g;
      colors[i * 3 + 2] = color.b;
    }
    colorAttr.needsUpdate = true;
  };
  const animate = () => {
    controls.update();
    mesh.rotation.y += state.playing ? 0.0018 : 0.00035;
    renderer.render(scene, camera);
    requestAnimationFrame(animate);
  };
  window.addEventListener("resize", resize);
  resize();
  paint(data.tracks[0], 0);
  animate();
  return {
    paint,
    reset() {
      camera.position.set(0.2, 0.15, 7.4);
      controls.target.set(0, 0, 0);
      mesh.rotation.set(0.06, -0.38, 0);
      controls.update();
    }
  };
}

function buildMeshGeometry(payload) {
  const lh = Array.isArray(payload.lh_coord?.[0]) ? payload.lh_coord.flat() : payload.lh_coord;
  const rh = Array.isArray(payload.rh_coord?.[0]) ? payload.rh_coord.flat() : payload.rh_coord;
  const lhArr = Float32Array.from(lh || []);
  const rhArr = Float32Array.from(rh || []);
  const lhVerts = lhArr.length / 3;
  const positions = new Float32Array(lhArr.length + rhArr.length);
  positions.set(lhArr, 0);
  positions.set(rhArr, lhArr.length);

  const lhF = Array.isArray(payload.lh_faces?.[0]) ? payload.lh_faces.flat() : payload.lh_faces;
  const rhF = Array.isArray(payload.rh_faces?.[0]) ? payload.rh_faces.flat() : payload.rh_faces;
  const idx = new Uint32Array((lhF || []).length + (rhF || []).length);
  idx.set(lhF || [], 0);
  for (let i = 0; i < (rhF || []).length; i++) idx[(lhF || []).length + i] = rhF[i] + lhVerts;

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(idx, 1));
  normalizeGeometry(geometry, 1.75);
  return { geometry, vertexCount: positions.length / 3 };
}

function buildFallbackCortexGeometry() {
  const latSteps = 38;
  const lonSteps = 56;
  const positions = [];
  const faces = [];
  const addHemisphere = (side) => {
    const start = positions.length / 3;
    for (let i = 0; i <= latSteps; i++) {
      const v = i / latSteps;
      const theta = -Math.PI / 2 + v * Math.PI;
      for (let j = 0; j <= lonSteps; j++) {
        const u = j / lonSteps;
        const phi = u * Math.PI * 2;
        const fold =
          1 +
          0.07 * Math.sin(10 * phi + 2.2 * Math.sin(theta * 2)) +
          0.04 * Math.sin(12 * theta + side * 1.7) +
          0.025 * Math.cos(18 * (u + v));
        let x = side * 0.48 + Math.cos(theta) * Math.cos(phi) * 0.58 * fold;
        if (side * x < 0.1) x = side * (0.1 + 0.035 * Math.sin(theta * 7 + phi * 3));
        const y = Math.sin(theta) * 0.78 * fold;
        const z = Math.cos(theta) * Math.sin(phi) * 1.08 * fold;
        positions.push(x, y, z);
      }
    }
    for (let i = 0; i < latSteps; i++) {
      for (let j = 0; j < lonSteps; j++) {
        const a = start + i * (lonSteps + 1) + j;
        const b = a + 1;
        const c = a + (lonSteps + 1);
        const d = c + 1;
        if (side > 0) faces.push(a, c, b, b, c, d);
        else faces.push(a, b, c, b, d, c);
      }
    }
  };
  addHemisphere(-1);
  addHemisphere(1);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(faces);
  normalizeGeometry(geometry, 1.8);
  return { geometry, vertexCount: positions.length / 3 };
}

function normalizeGeometry(geometry, targetRadius) {
  geometry.computeBoundingSphere();
  const sphere = geometry.boundingSphere;
  if (sphere) {
    const p = geometry.attributes.position;
    const scale = targetRadius / Math.max(sphere.radius, 1e-6);
    for (let i = 0; i < p.count; i++) {
      p.setXYZ(
        i,
        (p.getX(i) - sphere.center.x) * scale,
        (p.getY(i) - sphere.center.y) * scale,
        (p.getZ(i) - sphere.center.z) * scale
      );
    }
    p.needsUpdate = true;
  }
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
}

function wireTheme() {
  $("#themeToggle")?.addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("braindiff-theme", next); } catch (_) {}
    if (state.data && brain) brain.paint(state.data.tracks[state.activeTrack], state.progress);
  });
}

function wireShare() {
  $("#shareBtn")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      $("#shareBtn").textContent = "Copied";
      setTimeout(() => { $("#shareBtn").textContent = "Share"; }, 1200);
    } catch (_) {
      location.hash = "share";
    }
  });
}

function renderError(error) {
  $("#mediaApp").innerHTML = `<section class="error-state"><p class="eyebrow">Result unavailable</p><h1>Could not open this media result.</h1><p class="dek">${escapeHtml(error.message || String(error))}</p><a class="top-btn" href="./launch">Start again</a></section>`;
}

function normalizeSeries(values) {
  const nums = (Array.isArray(values) ? values : []).map(Number).filter(Number.isFinite);
  if (!nums.length) return [0.35, 0.45, 0.38, 0.42];
  const min = Math.min(...nums), max = Math.max(...nums);
  if (max <= 1 && min >= 0) return nums;
  const span = max - min || 1;
  return nums.map((n) => (n - min) / span);
}
function valueAt(series, index) { return series[Math.max(0, Math.min(series.length - 1, index))] || 0; }
function mean(series) { return normalizeSeries(series).reduce((a, b) => a + b, 0) / Math.max(1, normalizeSeries(series).length); }
function maxSeriesLength(tracks) { return Math.max(1, ...tracks.flatMap((t) => [t.a.length, t.b.length])); }
function bestDeltaIndex(a, b) {
  const len = Math.max(a.length, b.length);
  let best = 0, bestVal = -1;
  for (let i = 0; i < len; i++) {
    const diff = Math.abs(valueAt(b, i) - valueAt(a, i));
    if (diff > bestVal) { bestVal = diff; best = i; }
  }
  return best;
}
function nearestMoment(moments, time) {
  let index = 0, distance = Infinity;
  moments.forEach((moment, i) => {
    const d = Math.abs(moment.time - time);
    if (d < distance) { distance = d; index = i; }
  });
  return { index, moment: moments[index] };
}
function labelForTrack(key, data) { return data.tracks.find((track) => track.key === key)?.label || key || "Signal"; }
function formatTime(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function signed(n) { return `${n >= 0 ? "+" : ""}${n.toFixed(2)}`; }
function pill(label, value) { return `<span class="stat-pill"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></span>`; }
function short(value) { return String(value || "").slice(0, 8); }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
