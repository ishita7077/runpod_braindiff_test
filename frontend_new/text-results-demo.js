/**
 * Text results demo page — purpose-built for text comparison.
 *
 * Sections:
 *  01 / BRAIN     — 3D cortex viewer (shared with audio/video pages)
 *  02 / READ      — Side-by-side annotated text, each phrase colored by
 *                   its dominant cortical system
 *  03 / THE SIGNAL — 7-dim sparklines (A vs B timeseries)
 *  04 / FLOW      — Backend heatmap PNG (all dims × time)
 *  05 / PHRASES   — Peak divergence moments: exact text chunks where
 *                   the two versions differed most per dimension
 *  06 / WHAT TO WRITE — Actionable guidance from the insight engine
 */

import { mountCortex } from "./assets/cortex-viewer.js";

/* ─── DIM REGISTRY ────────────────────────────────────────────── */

const DIMS = {
  personal_resonance: {
    label: "Personal Resonance",
    desc: "How much the brain processes this as self-relevant (mPFC)",
    color: "#F59E0B",
    cssVar: "--dim-personal-resonance",
  },
  social_thinking: {
    label: "Social Thinking",
    desc: "How much the brain considers others' perspectives (TPJ)",
    color: "#8B5CF6",
    cssVar: "--dim-social-thinking",
  },
  brain_effort: {
    label: "Brain Effort",
    desc: "How hard the brain works to process this (dlPFC)",
    color: "#14B8A6",
    cssVar: "--dim-brain-effort",
  },
  language_depth: {
    label: "Language Depth",
    desc: "How deeply the brain extracts meaning (Broca's + Wernicke's)",
    color: "#10B981",
    cssVar: "--dim-language-depth",
  },
  gut_reaction: {
    label: "Gut Reaction",
    desc: "How viscerally the brain responds (anterior insula)",
    color: "#F43F5E",
    cssVar: "--dim-gut-reaction",
  },
  memory_encoding: {
    label: "Memory Encoding",
    desc: "How likely the brain is to commit this to long-term storage (left vlPFC)",
    color: "#3B82F6",
    cssVar: "--dim-memory-encoding",
  },
  attention_salience: {
    label: "Attention",
    desc: "How strongly the brain's attention system is engaged (dorsal attention network)",
    color: "#EAB308",
    cssVar: "--dim-attention-salience",
  },
};

const DIM_KEYS = Object.keys(DIMS);

/* ─── BOOTSTRAP ───────────────────────────────────────────────── */

const params = new URLSearchParams(location.search);
const jobId = params.get("job");
const isLocalhost = /^(localhost|127\.|0\.0\.0\.0)/.test(location.hostname);
if (!isLocalhost && !jobId) location.replace("/launch");

const DEMO_JOB = "5fd30256-1c2e-443a-b3d8-8da2f05abaa6";
const isDemo = isLocalhost && !jobId;

const $ = (s) => document.querySelector(s);

const state = { data: null, cortex: null };

boot();

async function boot() {
  wireTheme();
  wireShare();
  try {
    const rawJob = isDemo ? await fetchFromApi(DEMO_JOB) : await fetchFromApi(jobId);
    const data = adaptResult(rawJob);
    state.data = data;
    renderAll(data);
    state.cortex = await mountCortex({
      canvas: $("#brainCanvas"),
      vertexDeltaB64: data.vertex_delta_b64,
      vertexAB64: data.vertex_a_b64,
      vertexBB64: data.vertex_b_b64,
      roiHighlight: "language",
    });
    if (state.cortex && !state.cortex.isReal) {
      $("#brainCaption").textContent =
        "Cortical surface requires the production backend — vertex-level contrast unavailable here.";
      document.querySelector(".brain-canvas-wrap")?.setAttribute("data-state", "unavailable");
    }
    $("#resetBrain")?.addEventListener("click", () => state.cortex?.reset());
    document.querySelectorAll(".brain-view-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".brain-view-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.cortex?.setView(btn.dataset.view || "diff");
      });
    });
  } catch (err) {
    renderError(err);
  }
}

/* ─── DATA FETCH & ADAPT ──────────────────────────────────────── */

async function fetchFromApi(id) {
  const res = await fetch(`/api/diff/status/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Job could not load (HTTP ${res.status})`);
  const job = await res.json();
  if (job.status === "error") throw new Error(job.error?.message || "RunPod returned an error for this job.");
  if (job.status !== "done") throw new Error("This job is not finished yet. Open the run page and wait for completion.");
  return job;
}

function adaptResult(job) {
  const result = job.result || {};
  const meta = result.meta || {};
  return {
    kind: "text",
    job_id: job.job_id || jobId || DEMO_JOB,
    // text content
    text_a: meta.text_a || meta.transcript_a || "",
    text_b: meta.text_b || meta.transcript_b || "",
    text_a_timesteps: meta.text_a_timesteps || 0,
    text_b_timesteps: meta.text_b_timesteps || 0,
    // brain data
    headline: meta.headline || result.insights?.headline || "Text comparison complete.",
    sub: result.insights?.subhead || result.insights?.headline || "Two texts, one cortex.",
    atlas_peak: meta.atlas_peak || null,
    // heatmap PNG from matplotlib
    heatmap_b64: (meta.heatmap || {}).image_base64 || "",
    // 7-dim timeseries
    dimensions: Array.isArray(result.dimensions) ? result.dimensions : [],
    insights: result.insights || {},
    warnings: Array.isArray(result.warnings) ? result.warnings : [],
    // vertex data for 3D brain
    vertex_delta_b64: result.vertex_delta_b64 || "",
    vertex_a_b64: result.vertex_a_b64 || "",
    vertex_b_b64: result.vertex_b_b64 || "",
  };
}

/* ─── MAIN RENDER ─────────────────────────────────────────────── */

function renderAll(data) {
  // Headline section
  $("#pageHeadline").textContent = data.headline;
  $("#pageDek").textContent = data.sub;
  renderHeroStats(data);
  renderSampleCards(data);
  // Section 01 — brain recommendations
  renderRecommendations(data);
  // Section 02 — annotated text
  renderDimLegend();
  renderAnnotatedText(data);
  // Section 03 — sparklines
  renderSignalGrid(data);
  // Section 04 — heatmap
  renderFlowSection(data);
  // Section 05 — peak phrases
  renderPhraseGrid(data);
  // Section 06 — actionables
  renderActionables(data);
}

/* ─── HERO STATS ──────────────────────────────────────────────── */

function renderHeroStats(data) {
  const el = $("#heroStats");
  if (!el) return;
  const parts = [
    pill("Mode", "text"),
    pill("Job", isDemo ? "demo" : short(data.job_id)),
    data.text_a.length ? pill("A", `${data.text_a.length} chars`) : null,
    data.text_b.length ? pill("B", `${data.text_b.length} chars`) : null,
  ].filter(Boolean);
  el.innerHTML = parts.join("");
}

function renderSampleCards(data) {
  const textA = data.text_a;
  const textB = data.text_b;
  // Use first few words as name
  const nameA = data.insights?.what_changed?.[0]?.title || firstWords(textA, 5) || "Version A";
  const nameB = data.insights?.what_changed?.[1]?.title || firstWords(textB, 5) || "Version B";
  const na = $("#sampleNameA"); if (na) na.textContent = "Version A";
  const nb = $("#sampleNameB"); if (nb) nb.textContent = "Version B";
  const sa = $("#sampleStatsA"); if (sa) sa.textContent = textA.length ? `${textA.length} chars` : "—";
  const sb = $("#sampleStatsB"); if (sb) sb.textContent = textB.length ? `${textB.length} chars` : "—";
  const la = $("#textLabelA"); if (la) la.textContent = "Version A";
  const lb = $("#textLabelB"); if (lb) lb.textContent = "Version B";
  const ca = $("#textCharsA"); if (ca && textA.length) ca.textContent = `${textA.length} chars`;
  const cb = $("#textCharsB"); if (cb && textB.length) cb.textContent = `${textB.length} chars`;
}

/* ─── 01 / BRAIN: RECOMMENDATIONS ────────────────────────────── */

function renderRecommendations(data) {
  const actionables = (data.insights && data.insights.actionables) || [];
  const title = $("#decisionTitle");
  const list = $("#recommendations");
  if (!list) return;
  if (actionables.length === 0) {
    if (title) title.textContent = "Largest shifts between text A and text B.";
    list.innerHTML = `<li class="empty-line">No actionable insights available for this run yet.</li>`;
    return;
  }
  if (title) title.textContent = "What changed between A and B.";
  list.innerHTML = actionables
    .slice(0, 4)
    .map((a) => `<li><strong>${esc(a.title || "")}</strong>${a.body ? ` — ${esc(a.body)}` : ""}</li>`)
    .join("");
}

/* ─── 02 / READ: DIM LEGEND ──────────────────────────────────── */

function renderDimLegend() {
  const el = $("#dimLegend");
  if (!el) return;
  el.innerHTML = DIM_KEYS.map((key) => {
    const d = DIMS[key];
    return `<span class="dim-badge" style="--dim-color:${d.color}" title="${esc(d.desc)}">
      <span class="dim-dot" style="background:${d.color};box-shadow:0 0 6px ${d.color}88"></span>
      ${esc(d.label)}
    </span>`;
  }).join("");
}

/* ─── 02 / READ: ANNOTATED TEXT ──────────────────────────────── */

function renderAnnotatedText(data) {
  const bodyA = $("#textBodyA");
  const bodyB = $("#textBodyB");
  if (!bodyA || !bodyB) return;

  if (!data.text_a || !data.dimensions.length) {
    bodyA.innerHTML = `<p class="empty-line">No text available.</p>`;
    bodyB.innerHTML = `<p class="empty-line">No text available.</p>`;
    return;
  }

  const segsA = buildSegments(data.text_a, data.text_a_timesteps || data.dimensions[0]?.timeseries_a?.length || 1, data.dimensions, "a");
  const segsB = buildSegments(data.text_b, data.text_b_timesteps || data.dimensions[0]?.timeseries_b?.length || 1, data.dimensions, "b");

  bodyA.innerHTML = segsToHtml(segsA);
  bodyB.innerHTML = segsToHtml(segsB);
}

function buildSegments(text, nSteps, dimensions, side) {
  if (!text || nSteps < 1) return [{ dim: null, text }];
  const charsPerStep = text.length / nSteps;
  const tokens = text.match(/\S+|\s+/g) || [];
  const segments = [];
  let pos = 0;
  let curDim = null;
  let curText = "";

  for (const tok of tokens) {
    const isWord = /\S/.test(tok);
    if (isWord) {
      const step = Math.min(Math.floor(pos / charsPerStep), nSteps - 1);
      const dom = dominantDim(dimensions, side, step);
      if (dom !== curDim) {
        if (curText) segments.push({ dim: curDim, text: curText });
        curDim = dom;
        curText = tok;
      } else {
        curText += tok;
      }
    } else {
      curText += tok;
    }
    pos += tok.length;
  }
  if (curText) segments.push({ dim: curDim, text: curText });
  return segments;
}

function dominantDim(dimensions, side, step) {
  let maxVal = -1;
  let maxKey = null;
  for (const d of dimensions) {
    const ts = side === "a" ? (d.timeseries_a || []) : (d.timeseries_b || []);
    const v = Math.abs(ts[step] ?? 0);
    if (v > maxVal) { maxVal = v; maxKey = d.key || d.name; }
  }
  return maxKey;
}

function segsToHtml(segments) {
  return segments.map(({ dim, text }) => {
    if (!dim || !DIMS[dim]) return esc(text);
    const color = DIMS[dim].color;
    const label = DIMS[dim].label;
    const bg = hexToRgba(color, 0.10);
    const border = hexToRgba(color, 0.35);
    return `<span class="txt-seg" style="background:${bg};border-bottom:1.5px solid ${border};border-radius:2px;padding:0 1px" title="${esc(label)}">${esc(text)}</span>`;
  }).join("");
}

/* ─── 03 / THE SIGNAL: SPARKLINES ────────────────────────────── */

function renderSignalGrid(data) {
  const grid = $("#signalGrid");
  if (!grid) return;
  if (!data.dimensions.length) {
    grid.innerHTML = `<p class="empty-line">No dimension data available.</p>`;
    return;
  }

  grid.innerHTML = data.dimensions.map((dim) => {
    const dimKey = dim.key || dim.name;
    const meta = DIMS[dimKey] || { label: dim.label || dimKey, color: "#888", desc: dim.tooltip || "" };
    const tsA = dim.timeseries_a || [];
    const tsB = dim.timeseries_b || [];
    const meanA = mean(tsA);
    const meanB = mean(tsB);
    const delta = meanA - meanB;
    const winner = Math.abs(delta) < 0.01 ? "tie" : delta > 0 ? "a" : "b";
    const deltaStr = (delta >= 0 ? "+" : "") + delta.toFixed(2);
    const spark = makeSpark(tsA, tsB, meta.color);

    return `<div class="signal-card">
      <div class="signal-card-head">
        <span class="signal-dim-dot" style="background:${meta.color};box-shadow:0 0 6px ${meta.color}88"></span>
        <span class="signal-name">${esc(meta.label)}</span>
        <span class="signal-delta ${winner}" title="Mean A − Mean B">${deltaStr}</span>
      </div>
      ${spark}
      <div class="signal-footer">
        <span title="${esc(meta.desc)}">${tsA.length} steps</span>
        <span class="signal-winner ${winner}">${winner === "a" ? "A higher" : winner === "b" ? "B higher" : "Tied"}</span>
      </div>
    </div>`;
  }).join("");
}

function makeSpark(tsA, tsB, color) {
  const W = 240, H = 44;
  if (!tsA.length && !tsB.length) return `<svg class="signal-sparkline" viewBox="0 0 ${W} ${H}"></svg>`;
  const n = Math.max(tsA.length, tsB.length);
  const allVals = [...tsA, ...tsB].filter(isFinite);
  const mn = Math.min(...allVals);
  const mx = Math.max(...allVals);
  const range = mx - mn || 1;
  const pad = 4;

  const pts = (ts) => ts.map((v, i) => {
    const x = (i / Math.max(n - 1, 1)) * W;
    const y = H - pad - ((v - mn) / range) * (H - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  // Filled area between A and B
  const areaPath = (() => {
    if (!tsA.length || !tsB.length) return "";
    const topPts = tsA.map((v, i) => {
      const x = (i / Math.max(n - 1, 1)) * W;
      const y = H - pad - ((v - mn) / range) * (H - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const botPts = [...tsB].reverse().map((v, i) => {
      const idx = tsB.length - 1 - i;
      const x = (idx / Math.max(n - 1, 1)) * W;
      const y = H - pad - ((v - mn) / range) * (H - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    return `<polygon points="${[...topPts, ...botPts].join(' ')}" fill="${color}" opacity="0.07"/>`;
  })();

  return `<svg class="signal-sparkline" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    ${areaPath}
    ${tsB.length ? `<polyline points="${pts(tsB)}" fill="none" stroke="var(--b)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>` : ""}
    ${tsA.length ? `<polyline points="${pts(tsA)}" fill="none" stroke="var(--a)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>` : ""}
  </svg>`;
}

/* ─── 04 / FLOW: HEATMAP ─────────────────────────────────────── */

function renderFlowSection(data) {
  const el = $("#flowSection");
  if (!el) return;

  if (!data.heatmap_b64) {
    el.innerHTML = `<div class="empty-strip">Heatmap not available for this job.</div>`;
    return;
  }

  const peakLabel = data.atlas_peak
    ? (typeof data.atlas_peak === "string" ? data.atlas_peak : data.atlas_peak.label || "")
    : "";
  const peakHtml = peakLabel
    ? `<span class="heatmap-peak">Peak region: <strong>${esc(peakLabel)}</strong></span>`
    : "";

  el.innerHTML = `<div class="heatmap-wrap">
    <img src="data:image/png;base64,${data.heatmap_b64}" alt="Activation heatmap — 7 cortical dimensions across stimulus time" />
    <div class="heatmap-caption">
      <span>Row = cortical dimension · Column = timepoint · Warm colors = higher activation</span>
      ${peakHtml}
    </div>
  </div>`;
}

/* ─── 05 / PHRASES: PEAK DIVERGENCE ──────────────────────────── */

function renderPhraseGrid(data) {
  const grid = $("#phraseGrid");
  if (!grid) return;

  if (!data.dimensions.length || !data.text_a || !data.text_b) {
    grid.innerHTML = `<div class="empty-strip">No phrase data available.</div>`;
    return;
  }

  // For each dim, find the timestep with max |tsA[t] - tsB[t]|
  const cards = data.dimensions
    .map((dim) => {
      const dimKey = dim.key || dim.name;
      const meta = DIMS[dimKey] || { label: dim.label || dimKey, color: "#888" };
      const tsA = dim.timeseries_a || [];
      const tsB = dim.timeseries_b || [];
      const n = Math.min(tsA.length, tsB.length);
      if (n === 0) return null;

      let maxDelta = -1, peakStep = 0;
      for (let t = 0; t < n; t++) {
        const d = Math.abs((tsA[t] ?? 0) - (tsB[t] ?? 0));
        if (d > maxDelta) { maxDelta = d; peakStep = t; }
      }

      const chunkA = extractChunk(data.text_a, peakStep, data.text_a_timesteps || tsA.length);
      const chunkB = extractChunk(data.text_b, peakStep, data.text_b_timesteps || tsB.length);

      return { meta, dim, maxDelta, peakStep, chunkA, chunkB };
    })
    .filter(Boolean)
    .sort((a, b) => b.maxDelta - a.maxDelta)
    .slice(0, 6);

  if (!cards.length) {
    grid.innerHTML = `<div class="empty-strip">No divergence phrases could be computed.</div>`;
    return;
  }

  grid.innerHTML = cards.map(({ meta, maxDelta, chunkA, chunkB }) => {
    const deltaLabel = `Δ ${maxDelta.toFixed(2)}`;
    return `<div class="phrase-card">
      <div class="phrase-card-head">
        <span class="phrase-dim-dot" style="background:${meta.color};box-shadow:0 0 5px ${meta.color}88"></span>
        <span class="phrase-dim-name">${esc(meta.label)}</span>
        <span class="phrase-delta-badge">${esc(deltaLabel)}</span>
      </div>
      <div class="phrase-quotes">
        <div class="phrase-quote">
          <div class="phrase-quote-label a">A</div>
          <div class="phrase-quote-text">"${esc(chunkA)}"</div>
        </div>
        <div class="phrase-quote">
          <div class="phrase-quote-label b">B</div>
          <div class="phrase-quote-text">"${esc(chunkB)}"</div>
        </div>
      </div>
    </div>`;
  }).join("");
}

function extractChunk(text, step, nSteps) {
  if (!text || nSteps < 1) return text.slice(0, 60) + "…";
  const charsPerStep = text.length / nSteps;
  const start = Math.max(0, Math.floor((step - 0.5) * charsPerStep));
  const end = Math.min(text.length, Math.floor((step + 1.5) * charsPerStep));
  let chunk = text.slice(start, end).trim();
  // Clean to word boundaries
  if (start > 0) chunk = chunk.replace(/^\S+\s/, "");
  if (end < text.length) chunk = chunk.replace(/\s\S+$/, "");
  return chunk.length > 120 ? chunk.slice(0, 120) + "…" : chunk || text.slice(0, 60);
}

/* ─── 06 / WHAT TO WRITE: ACTIONABLES ────────────────────────── */

function renderActionables(data) {
  const grid = $("#actionablesGrid");
  const aside = $("#insightsAside");
  const actionables = data.insights?.actionables || [];

  if (grid) {
    if (!actionables.length) {
      grid.innerHTML = `<div class="empty-strip">No actionable guidance available for this run.</div>`;
    } else {
      grid.innerHTML = actionables.map((a, i) => `<div class="action-card">
        <div class="action-num">0${i + 1}</div>
        <h3 class="action-title">${esc(a.title || "")}</h3>
        ${a.body ? `<p class="action-body">${esc(a.body)}</p>` : ""}
      </div>`).join("");
    }
  }

  if (aside) {
    const boxes = [];
    if (data.insights?.cool_factor) {
      boxes.push({ label: "Cool factor", text: data.insights.cool_factor });
    }
    if (data.insights?.scientific_note) {
      boxes.push({ label: "Scientific note", text: data.insights.scientific_note });
    }
    if (boxes.length) {
      aside.innerHTML = boxes.map((b) => `<div class="insight-box">
        <div class="insight-box-label">${esc(b.label)}</div>
        <p class="insight-box-text">${esc(b.text)}</p>
      </div>`).join("");
    } else {
      aside.hidden = true;
    }
  }
}

/* ─── ERROR STATE ─────────────────────────────────────────────── */

function renderError(err) {
  const app = $("#mediaApp");
  if (!app) return;
  app.innerHTML = `<div class="error-state">
    <p class="micro">Error</p>
    <h2>${esc(err.message || "Something went wrong.")}</h2>
    <p>Check that the backend is running and the job ID is correct, then reload.</p>
    <a class="top-btn" href="./launch">New comparison</a>
  </div>`;
}

/* ─── SHARE / THEME ───────────────────────────────────────────── */

function wireShare() {
  const btn = $("#shareBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const url = location.href;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(() => {
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Share"; }, 1600);
      });
    }
  });
}

function wireTheme() {
  const btn = $("#themeToggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const root = document.documentElement;
    if (root.getAttribute("data-theme") === "dark") {
      root.removeAttribute("data-theme");
      localStorage.setItem("braindiff-theme", "light");
    } else {
      root.setAttribute("data-theme", "dark");
      localStorage.setItem("braindiff-theme", "dark");
    }
  });
}

/* ─── UTILITIES ───────────────────────────────────────────────── */

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function pill(label, value) {
  return `<span class="stat-pill"><strong>${esc(value)}</strong> ${esc(label)}</span>`;
}

function short(id) {
  return id ? String(id).slice(0, 8) : "—";
}

function firstWords(text, n) {
  return text.trim().split(/\s+/).slice(0, n).join(" ");
}

function mean(arr) {
  if (!arr.length) return 0;
  return arr.reduce((s, v) => s + (v ?? 0), 0) / arr.length;
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}
