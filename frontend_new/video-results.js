/**
 * Video results page — engineered for video specifically.
 *
 * Real data only. If the worker didn't return a piece (keyframes, peak
 * moments, transcript), the corresponding section renders an empty state.
 * We do not invent scene names, beat descriptions, or moment prose.
 *
 * Page-specific concerns (not shared with audio):
 *  - Real keyframe thumbnails from ffmpeg scene-detection, embedded as
 *    base64 in the worker meta. Click a keyframe → playhead jumps there.
 *  - Scene timeline showing real ffmpeg scdet boundaries (when present)
 *    instead of "Opening beat / Middle proof / Human read / Final frame".
 *  - Transcript still rendered (video has audio track) but visual-first:
 *    keyframes lead, transcript secondary.
 *  - Visual-cortex / MT emphasis on the cortex viewer.
 */
import { mountCortex } from "./assets/cortex-viewer.js";
import { renderPatternStrip } from "./assets/patterns.js";
import { renderConnectivity } from "./assets/connectivity-graph.js";

const params = new URLSearchParams(location.search);
const jobId = params.get("job");
const isDemo = params.get("demo") === "1" || !jobId;

const $ = (sel) => document.querySelector(sel);

const state = {
  data: null,
  cortex: null,
  progress: 0,
  activeMoment: -1,
  playing: false,
  tickTimer: 0,
};

boot();

async function boot() {
  wireTheme();
  wireShare();
  try {
    const data = isDemo ? await fetchDemo() : await fetchJob(jobId);
    state.data = data;
    render(data);
    state.cortex = await mountCortex({
      canvas: $("#brainCanvas"),
      vertexDeltaB64: data.vertex_delta_b64,
      vertexAB64: data.vertex_a_b64,
      vertexBB64: data.vertex_b_b64,
      roiHighlight: "visual",
    });
    if (state.cortex && !state.cortex.isReal) {
      $("#brainCaption").textContent =
        "Approximate cortical surface — atlas-aligned activations not available on this build.";
    }
    $("#resetBrain")?.addEventListener("click", () => state.cortex?.reset());
  } catch (err) {
    renderError(err);
  }
}

async function fetchDemo() {
  const res = await fetch("./demo/video-result.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`Demo data could not load (${res.status})`);
  return res.json();
}

async function fetchJob(id) {
  const res = await fetch(`/api/diff/status/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Job could not load (${res.status})`);
  const job = await res.json();
  if (job.status === "error") throw new Error(job.error?.message || "RunPod returned an error for this job.");
  if (job.status !== "done") throw new Error("This job is not finished yet. Open the run page and wait for completion.");
  return adaptResult(job);
}

function adaptResult(job) {
  const result = job.result || {};
  const meta = result.meta || {};
  const features = meta.media_features || {};
  return {
    kind: "video",
    job_id: job.job_id || jobId,
    headline: meta.headline || "Video comparison complete.",
    sub: insightSubhead(result),
    samples: {
      a: {
        label: "A",
        name: meta.media_name_a || meta.media_filename_a || "Sample A",
        duration: Number(meta.media_duration_a_s) || 0,
        keyframes: Array.isArray(features.keyframes_a) ? features.keyframes_a : [],
        transcript_segments: Array.isArray(meta.transcript_segments_a) ? meta.transcript_segments_a : [],
      },
      b: {
        label: "B",
        name: meta.media_name_b || meta.media_filename_b || "Sample B",
        duration: Number(meta.media_duration_b_s) || 0,
        keyframes: Array.isArray(features.keyframes_b) ? features.keyframes_b : [],
        transcript_segments: Array.isArray(meta.transcript_segments_b) ? meta.transcript_segments_b : [],
      },
    },
    dimensions: Array.isArray(result.dimensions) ? result.dimensions : [],
    moments: Array.isArray(features.moments) ? features.moments : [],
    patterns: features.patterns && typeof features.patterns === "object" ? features.patterns : { a: [], b: [] },
    connectivity: features.connectivity && typeof features.connectivity === "object" ? features.connectivity : null,
    insights: result.insights || {},
    warnings: Array.isArray(result.warnings) ? result.warnings : [],
    vertex_delta_b64: result.vertex_delta_b64 || "",
    vertex_a_b64: result.vertex_a_b64 || "",
    vertex_b_b64: result.vertex_b_b64 || "",
  };
}

function insightSubhead(result) {
  return result?.insights?.headline ||
    "Two cuts, one cortex. Scrub the timeline to inspect where the response shifts.";
}

function render(data) {
  $("#pageHeadline").textContent = data.headline;
  $("#pageDek").textContent = data.sub;
  renderHeroStats(data);
  renderRecommendations(data);
  renderSample("#sampleA", data.samples.a);
  renderSample("#sampleB", data.samples.b);
  renderTracks(data);
  renderMoments(data);
  renderScenePair(data);
  renderPatterns(data);
  wireTimeline(data);
}

function renderPatterns(data) {
  const totalA = data.samples.a.duration || 30;
  const totalB = data.samples.b.duration || 30;
  const stripA = document.getElementById("patternStripA");
  const stripB = document.getElementById("patternStripB");
  if (stripA) renderPatternStrip(stripA, data.patterns.a || [], totalA);
  if (stripB) renderPatternStrip(stripB, data.patterns.b || [], totalB);
  // Connectivity map
  const connRoot = document.getElementById("connectivitySection");
  if (connRoot && data.connectivity) {
    renderConnectivity(connRoot, data.connectivity, {
      labelA: data.samples.a.name || "Cut A",
      labelB: data.samples.b.name || "Cut B",
    });
  } else if (connRoot) {
    connRoot.hidden = true;
  }
}

function renderHeroStats(data) {
  const bits = [
    pill("Mode", "video"),
    pill("Job", isDemo ? "demo" : short(data.job_id)),
    data.samples.a.duration ? pill("A", fmtTime(data.samples.a.duration)) : null,
    data.samples.b.duration ? pill("B", fmtTime(data.samples.b.duration)) : null,
  ].filter(Boolean);
  $("#heroStats").innerHTML = bits.join("");
}

function renderRecommendations(data) {
  const actionables = (data.insights && data.insights.actionables) || [];
  if (actionables.length === 0) {
    $("#decisionTitle").textContent = "Largest shifts between cut A and cut B.";
    $("#recommendations").innerHTML =
      `<li class="empty-line">No actionable insights available for this run yet.</li>`;
    return;
  }
  $("#decisionTitle").textContent = "What changed between A and B.";
  $("#recommendations").innerHTML = actionables
    .slice(0, 4)
    .map((a) => `<li><strong>${escapeHtml(a.title || "")}</strong>${a.body ? ` — ${escapeHtml(a.body)}` : ""}</li>`)
    .join("");
}

function renderSample(selector, sample) {
  const root = $(selector);
  if (!root) return;
  const keyStrip = sample.keyframes.length
    ? `<div class="keyframe-strip" aria-label="Keyframes">${sample.keyframes
        .map(
          (kf) => `
            <button class="keyframe" type="button" data-time="${kf.time}" title="${fmtTime(kf.time)}">
              <img src="data:image/jpeg;base64,${kf.image_base64}" alt="" />
              <span>${fmtTime(kf.time)}</span>
            </button>
          `
        )
        .join("")}</div>`
    : `<div class="empty-strip">Keyframes not available — ffmpeg scene-detection returned nothing for this clip.</div>`;
  const transcript = sample.transcript_segments.length
    ? `<details class="transcript-details">
        <summary>Transcript (${sample.transcript_segments.length} phrases)</summary>
        <div class="transcript-lines">${sample.transcript_segments
          .map(
            (seg) =>
              `<button class="transcript-line" type="button" data-time="${seg.start}">${fmtTime(seg.start)} · ${escapeHtml(
                seg.text || ""
              )}</button>`
          )
          .join("")}</div>
      </details>`
    : "";
  const summaryBits = [];
  if (sample.duration) summaryBits.push(fmtTime(sample.duration));
  if (sample.keyframes.length) summaryBits.push(`${sample.keyframes.length} keyframes`);
  root.innerHTML = `
    <div class="sample-head">
      <div class="sample-badge">${sample.label}</div>
      <div style="min-width:0;flex:1">
        <div class="sample-name">${escapeHtml(sample.name)}</div>
        <div class="sample-meta">${summaryBits.join(" · ") || "—"}</div>
      </div>
    </div>
    ${keyStrip}
    ${transcript}
  `;
}

function renderTracks(data) {
  const root = $("#tracks");
  if (!root) return;
  if (!data.dimensions.length) {
    root.innerHTML = `<div class="empty-strip">No dimensional data returned for this run.</div>`;
    return;
  }
  root.innerHTML = data.dimensions
    .map((dim, i) => {
      const a = mean(dim.timeseries_a || []);
      const b = mean(dim.timeseries_b || []);
      const delta = b - a;
      return `
        <button class="track-row" type="button" data-track="${i}" data-track-key="${escapeHtml(dim.key || "")}">
          <span class="track-label">
            <strong>${escapeHtml(dim.label || dim.key || `Track ${i + 1}`)}</strong>
            <span>${escapeHtml(dim.region || "")}</span>
          </span>
          <span class="track-bars">
            <span class="track-line a"><span style="--w:${a.toFixed(3)}"></span></span>
            <span class="track-line b"><span style="--w:${b.toFixed(3)}"></span></span>
          </span>
          <span class="track-score"><strong>${signed(delta)}</strong><span>B-A</span></span>
        </button>
      `;
    })
    .join("");
}

function renderMoments(data) {
  const root = $("#moments");
  if (!root) return;
  if (!data.moments.length) {
    root.innerHTML = `<div class="empty-strip">No peak-Δ moments detected — contrast is uniform across the cut.</div>`;
    return;
  }
  const dimMap = new Map();
  for (const dim of data.dimensions) dimMap.set(dim.key, dim);
  // Find a keyframe near each moment, prefer the side that "won" the moment.
  function frameForMoment(m) {
    const list = m.sample === "B" ? data.samples.b.keyframes : data.samples.a.keyframes;
    if (!list.length) return null;
    let best = list[0];
    let bestD = Math.abs((best.time || 0) - m.time);
    for (const kf of list) {
      const d = Math.abs((kf.time || 0) - m.time);
      if (d < bestD) { best = kf; bestD = d; }
    }
    return best;
  }
  root.innerHTML = data.moments
    .map((m, i) => {
      const dim = dimMap.get(m.track) || {};
      const dimLabel = dim.label || m.track || "Cortical contrast";
      const region = dim.region || "";
      const sideClass = m.sample === "B" ? "winner-b" : "winner-a";
      const directionWord = m.sample === "B" ? "stronger in B" : "stronger in A";
      const frame = frameForMoment(m);
      const thumb = frame
        ? `<img class="moment-thumb" src="data:image/jpeg;base64,${frame.image_base64}" alt="" />`
        : "";
      return `
        <article class="moment-card ${sideClass}" data-moment="${i}" data-time="${m.time}">
          ${thumb}
          <div class="moment-meta">
            <span>${m.sample} · ${fmtTime(m.time)}</span>
            <span>${escapeHtml(dimLabel)}</span>
          </div>
          <h3>${escapeHtml(dimLabel)} — ${directionWord}</h3>
          <p>Δ ${signed(m.delta)} on the ${escapeHtml(dimLabel.toLowerCase())} system${region ? ` (${escapeHtml(region)})` : ""}.</p>
        </article>
      `;
    })
    .join("");
}

function renderScenePair(data) {
  const root = $("#sceneMap");
  if (!root) return;
  const aFrames = data.samples.a.keyframes;
  const bFrames = data.samples.b.keyframes;
  if (!aFrames.length && !bFrames.length) {
    root.innerHTML = `<div class="empty-strip">No keyframes returned by ffmpeg.</div>`;
    return;
  }
  const rows = Math.max(aFrames.length, bFrames.length);
  const html = [];
  for (let i = 0; i < rows; i += 1) {
    html.push(`<div class="scene-pair">${frameBox(aFrames[i], "a")}${frameBox(bFrames[i], "b")}</div>`);
  }
  root.innerHTML = html.join("");
}

function frameBox(kf, side) {
  if (!kf) {
    return `<div class="scene-box ${side}"><div class="time">${side.toUpperCase()} · —</div><h3>No matched frame</h3><p>This side has no equivalent keyframe here.</p></div>`;
  }
  return `
    <div class="scene-box ${side}" data-time="${kf.time}">
      <img src="data:image/jpeg;base64,${kf.image_base64}" alt="" />
      <div class="time">${side.toUpperCase()} · ${fmtTime(kf.time)}</div>
    </div>
  `;
}

function wireTimeline(data) {
  const scrubber = $("#scrubber");
  if (scrubber) {
    scrubber.addEventListener("input", () => updatePlayhead(Number(scrubber.value) / 100));
  }
  document.addEventListener("click", (event) => {
    const timed = event.target.closest("[data-time]");
    if (!timed) return;
    const maxDuration = Math.max(data.samples.a.duration, data.samples.b.duration, 1);
    const t = Number(timed.dataset.time);
    if (!isFinite(t)) return;
    if (scrubber) scrubber.value = String(Math.round((t / maxDuration) * 100));
    updatePlayhead(t / maxDuration);
  });
  $("#playBtn")?.addEventListener("click", togglePlay);
}

function togglePlay() {
  const btn = $("#playBtn");
  state.playing = !state.playing;
  btn.classList.toggle("is-playing", state.playing);
  btn.textContent = state.playing ? "Pause" : "Play";
  clearInterval(state.tickTimer);
  if (!state.playing) return;
  const maxDuration = Math.max(state.data.samples.a.duration, state.data.samples.b.duration, 1);
  const stepPct = 100 / Math.max(1, Math.floor(maxDuration * 5));
  state.tickTimer = setInterval(() => {
    const scrubber = $("#scrubber");
    if (!scrubber) return;
    const next = Number(scrubber.value) + stepPct;
    if (next >= 100) {
      scrubber.value = "0";
      clearInterval(state.tickTimer);
      state.playing = false;
      $("#playBtn").classList.remove("is-playing");
      $("#playBtn").textContent = "Play";
      updatePlayhead(0);
      return;
    }
    scrubber.value = String(next);
    updatePlayhead(next / 100);
  }, 200);
}

function updatePlayhead(progress) {
  state.progress = Math.max(0, Math.min(1, progress));
  const data = state.data;
  if (!data) return;
  const aTime = data.samples.a.duration * state.progress;
  const bTime = data.samples.b.duration * state.progress;
  $("#timeA").textContent = `A ${fmtTime(aTime)}`;
  $("#timeB").textContent = `B ${fmtTime(bTime)}`;
  const maxTime = Math.max(aTime, bTime);
  document.querySelectorAll(".keyframe").forEach((node) => {
    const t = Number(node.dataset.time || 0);
    node.classList.toggle("is-hot", Math.abs(t - maxTime) < 4);
  });
  document.querySelectorAll(".scene-box").forEach((node) => {
    const t = Number(node.dataset.time || 0);
    node.classList.toggle("is-hot", Math.abs(t - maxTime) < 4);
  });
  document.querySelectorAll(".transcript-line").forEach((node) => {
    const t = Number(node.dataset.time || 0);
    node.classList.toggle("is-hot", Math.abs(t - maxTime) < 4);
  });
  const nearest = nearestMoment(data.moments, maxTime);
  state.activeMoment = nearest.index;
  document.querySelectorAll(".moment-card").forEach((card, i) => {
    card.classList.toggle("is-active", i === nearest.index);
  });
}

function nearestMoment(moments, t) {
  let best = -1, bestD = Infinity;
  for (let i = 0; i < moments.length; i += 1) {
    const d = Math.abs((moments[i].time || 0) - t);
    if (d < bestD) { bestD = d; best = i; }
  }
  return { index: best, moment: moments[best] || null };
}

function renderError(error) {
  $("#mediaApp").innerHTML = `
    <section class="error-state">
      <p class="eyebrow">Result unavailable</p>
      <h1>Could not open this video result.</h1>
      <p class="dek">${escapeHtml(error?.message || String(error))}</p>
      <a class="top-btn" href="./launch">Start again</a>
    </section>
  `;
}

function wireTheme() {
  $("#themeToggle")?.addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    if (next === "dark") root.setAttribute("data-theme", "dark");
    else root.removeAttribute("data-theme");
    try { localStorage.setItem("braindiff-theme", next); } catch (_) {}
    window.dispatchEvent(new CustomEvent("braindiff:theme", { detail: { theme: next } }));
  });
}

function wireShare() {
  $("#shareBtn")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(location.href);
      const btn = $("#shareBtn");
      const orig = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = orig; }, 1200);
    } catch (_) {
      location.hash = "share";
    }
  });
}

// ---- helpers ---------------------------------------------------------------
function fmtTime(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function signed(n) { const v = Number(n) || 0; return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`; }
function pill(label, value) { return `<span class="stat-pill"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></span>`; }
function short(value) { return String(value || "").slice(0, 8); }
function mean(xs) {
  if (!Array.isArray(xs) || xs.length === 0) return 0;
  let total = 0;
  let count = 0;
  for (const v of xs) {
    const n = Number(v);
    if (Number.isFinite(n)) { total += n; count += 1; }
  }
  return count ? total / count : 0;
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
