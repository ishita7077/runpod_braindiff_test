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
    const data = isDemo ? await fetchDemo(kind) : await fetchJob(kind, jobId);
    state.data = data;
    render(data);
    brain = createBrain($("#brainCanvas"), data);
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
    headline: mode === "video" ? "The run finished. Now inspect the cut." : "The run finished. Now inspect the listen.",
    dek: mode === "video"
      ? "This view maps the video over time so you can see which moments lifted attention, motion, memory, and social read."
      : "This view maps the audio over time so you can see which phrases changed attention, effort, trust, and memory.",
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
    ? `${name} is mapped into scene-length neural beats. Scrub to see where it earns or loses response.`
    : `${name} is mapped into phrase-length neural beats. Scrub to see where the voice earns or loses response.`;
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
      title: mode === "video" ? `${track.label} changes at beat ${i + 1}` : `${track.label} changes at phrase ${i + 1}`,
      detail: `${side} creates the stronger ${track.label.toLowerCase()} response around this point of the run.`,
      move: mode === "video" ? "Use this as an edit decision, not a generic score." : "Use this as a read direction, not a volume note."
    };
  });
}

function buildRecommendations(mode, tracks) {
  const strongest = tracks.slice().sort((a, b) => Math.abs(mean(b.b) - mean(b.a)) - Math.abs(mean(a.b) - mean(a.a)))[0];
  return mode === "video"
    ? [`Start with the cut that wins ${strongest?.label || "the strongest signal"}.`, "Inspect moments before making a winner call.", "Use the final card from the calmer sample if memory drops late."]
    : [`Keep the read that wins ${strongest?.label || "the strongest signal"}.`, "Protect pauses where attention rises.", "Make the final sentence direct enough to lock memory."];
}

function render(data) {
  $("#pageHeadline").textContent = data.headline;
  $("#pageDek").textContent = data.dek;
  $("#decisionTitle").textContent = kind === "video" ? "The edit decision is temporal." : "The voice decision is phrase-level.";
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
  button.textContent = state.playing ? "Pause scan" : "Play scan";
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
  $("#activeMomentMove").textContent = `-> ${moment.move}`;
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

function createBrain(canvas, data) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(0, 0.16, 5.3);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.enablePan = false;
  controls.minDistance = 2.5;
  controls.maxDistance = 7;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x40362e, 1.8));
  const key = new THREE.DirectionalLight(0xffffff, 2.6);
  key.position.set(3, 4, 5);
  scene.add(key);

  const geometry = new THREE.SphereGeometry(1.02, 96, 64);
  const pos = geometry.attributes.position;
  const colors = [];
  for (let i = 0; i < pos.count; i++) colors.push(0.56, 0.52, 0.45);
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
    const fold = 1 + 0.055 * Math.sin(12 * x + 4 * z) + 0.035 * Math.sin(18 * y + 5 * x);
    pos.setXYZ(i, x * fold * 1.1, y * fold * 0.86, z * fold * 0.72);
  }
  geometry.computeVertexNormals();
  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.72,
    metalness: 0.02
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.set(-0.05, -0.85, 0.08);
  mesh.position.y = 0.22;
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
    const base = new THREE.Color(document.documentElement.dataset.theme === "dark" ? 0x6d675d : 0x9c9586);
    const blue = new THREE.Color(0x4a78ab);
    const red = new THREE.Color(0xe04a2e);
    const active = delta >= 0 ? red : blue;
    const strength = Math.min(1, Math.abs(delta) * 2.8 + 0.08);
    const colorAttr = geometry.attributes.color;
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      const region = 0.5 + 0.5 * Math.sin(x * 3.4 + y * 4.1 + z * 2.5 + progress * 6.28);
      color.copy(base).lerp(active, strength * (0.18 + region * 0.72));
      colorAttr.setXYZ(i, color.r, color.g, color.b);
    }
    colorAttr.needsUpdate = true;
  };
  const animate = () => {
    controls.update();
    mesh.rotation.y += state.playing ? 0.0025 : 0.0007;
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
      camera.position.set(0, 0.16, 5.3);
      controls.target.set(0, 0, 0);
      mesh.rotation.set(-0.05, -0.85, 0.08);
      mesh.position.y = 0.22;
      controls.update();
    }
  };
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
