const textA = document.getElementById("textA");
const textB = document.getElementById("textB");
const countA = document.getElementById("countA");
const countB = document.getElementById("countB");
const runBtn = document.getElementById("runBtn");
const retryBtn = document.getElementById("retryBtn");
const landingEl = document.getElementById("landing");
const loadingEl = document.getElementById("loading");
const resultEl = document.getElementById("result");
const loadingSteps = document.getElementById("loadingSteps");
const loadingHintEl = document.getElementById("loadingHint");
const ctaNote = document.querySelector(".cta-note");
const headlineEl = document.getElementById("headline");
const winnerEl = document.getElementById("winner");
const subheadEl = document.getElementById("subhead");
const heroMetricsEl = document.getElementById("heroMetrics");
const barsEl = document.getElementById("bars");
const whatChangedEl = document.getElementById("whatChanged");
const whatStayedSimilarEl = document.getElementById("whatStayedSimilar");
const actionablesEl = document.getElementById("actionables");
const coolFactorEl = document.getElementById("coolFactor");
const scientificNoteEl = document.getElementById("scientificNote");
const heatmapImg = document.getElementById("heatmapImg");
const shareBtn = document.getElementById("shareBtn");

const runMeta = document.getElementById("runMeta");
const diagToggle = document.getElementById("diagToggle");
const diagClose = document.getElementById("diagClose");
const diagBackdrop = document.getElementById("diagBackdrop");
const diagDrawer = document.getElementById("diagDrawer");
const diagRefresh = document.getElementById("diagRefresh");
const diagShortcut = document.getElementById("diagShortcut");
const preflightStatus = document.getElementById("preflightStatus");
const preflightList = document.getElementById("preflightList");
const currentRunStatus = document.getElementById("currentRunStatus");
const currentRunPanel = document.getElementById("currentRunPanel");
const recentRuns = document.getElementById("recentRuns");
const loadingTelemetry = document.getElementById("loadingTelemetry");
const resultJson = document.getElementById("resultJson");
const heroCanvas = document.getElementById("heroCanvas");
const exampleBtns = [...document.querySelectorAll(".example")];
const apiReadyPill = document.getElementById("apiReadyPill");
const dimensionRadar = document.getElementById("dimensionRadar");
const atlasPeakLabel = document.getElementById("atlasPeakLabel");
const brainDualWrap = document.getElementById("brainDualWrap");
const dualBrain3dEl = document.getElementById("dualBrain3d");
const brainViewerLabelA = document.getElementById("brainViewerLabelA");
const bwrLegendHint = document.getElementById("bwrLegendHint");

const DUAL_3D_STORAGE_KEY = "braindiff_dual_3d";
const LOADING_FACTS_URL = "/data/tribe_loading_facts.json";

let loadingBrainDispose = null;
let loadingFactsTimer = null;

let isSubmitting = false;
let lastBrainPayload = null;
let preflightState = null;
let latestShareData = null;

const DEFAULT_SLOW_NOTICE_MS = 180_000;
const DEFAULT_HARD_TIMEOUT_MS = 1_200_000;

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function truncate(value, max = 120) {
  const text = String(value ?? "").trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function updateFormState() {
  countA.textContent = `${textA.value.length} / 5000`;
  countB.textContent = `${textB.value.length} / 5000`;
  const hasContent = !!textA.value.trim() && !!textB.value.trim();
  // Only block on real blockers. accelerate_missing on cpu runtime is not a blocker.
  const blockers = preflightState?.blockers || [];
  const realBlockers = blockers.filter((b) => b !== "accelerate_missing");
  const modelBlockers = preflightState ? realBlockers.length > 0 : false;
  runBtn.disabled = !hasContent || modelBlockers || isSubmitting;
}

function formatJobError(errorPayload) {
  const code = errorPayload?.code;
  if (code === "HF_AUTH_REQUIRED") return "Model access required. Authenticate HuggingFace for the gated text encoder.";
  if (code === "FFMPEG_REQUIRED") return "ffmpeg is missing for text-to-speech transcription.";
  if (code === "UVX_REQUIRED") return "uv/uvx is missing (needed for WhisperX transcription). Install uv in your venv.";
  if (code === "WHISPERX_FAILED")
    return "Transcription (WhisperX) failed. On Mac, Whisper uses CPU; check logs or try a smaller TRIBEV2_WHISPERX_MODEL.";
  if (code === "LLAMA_LOAD_FAILED") return "Llama text encoder failed to load or move to device. See server logs; try BRAIN_DIFF_MPS_TEXT_MAX_MEMORY on Mac.";
  if (code === "ATLAS_MAPPING_ERROR") return "Atlas mapping failed. Check HCP atlas files and labels.";
  return errorPayload?.message || "Diff job failed";
}

function resetLoadingSteps() {
  loadingSteps.querySelectorAll("li").forEach((li) => {
    li.classList.remove("done");
    li.textContent = li.textContent.replace(/^✓\s*/, "");
  });
  loadingHintEl.textContent = "";
  retryBtn.classList.add("hidden");
}

function markLoadingStep(status) {
  const target = loadingSteps.querySelector(`[data-step="${status}"]`);
  if (!target) return;
  target.classList.add("done");
  target.textContent = `✓ ${target.textContent.replace(/^✓\s*/, "")}`;
}

function renderMetricCards(metrics) {
  heroMetricsEl.innerHTML = "";
  (metrics || []).forEach((metric) => {
    const card = document.createElement("div");
    card.className = "metric-card";
    card.innerHTML = `
      <span class="metric-label">${escapeHtml(metric.label)}</span>
      <span class="metric-value">${escapeHtml(metric.value)}</span>
      <span class="metric-detail">${escapeHtml(metric.detail)}</span>
    `;
    heroMetricsEl.appendChild(card);
  });
}

const RADAR_DIM_ORDER = [
  "personal_resonance",
  "social_thinking",
  "brain_effort",
  "language_depth",
  "gut_reaction"
];

function renderDimensionRadar(dimensions) {
  const canvas = dimensionRadar;
  if (!canvas?.getContext) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const cx = w / 2;
  const cy = h / 2;
  const R = Math.min(w, h) * 0.36;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "rgba(5,5,5,0.8)";
  ctx.fillRect(0, 0, w, h);
  const byKey = Object.fromEntries((dimensions || []).map((d) => [d.key, d]));
  const n = RADAR_DIM_ORDER.length;
  const angles = Array.from({ length: n }, (_, i) => (-Math.PI / 2) + (i * 2 * Math.PI) / n);
  const vals = RADAR_DIM_ORDER.map((k) => {
    const row = byKey[k];
    if (!row) return 0;
    return Math.min(1, Math.max(0, Number(row.bar_fraction ?? row.magnitude ?? 0)));
  });

  ctx.strokeStyle = "rgba(255, 255, 255, 0.1)";
  ctx.lineWidth = 0.5;
  for (let ring = 1; ring <= 4; ring += 1) {
    const r = (R * ring) / 4;
    ctx.beginPath();
    angles.forEach((ang, i) => {
      const x = cx + r * Math.cos(ang);
      const y = cy + r * Math.sin(ang);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.stroke();
  }
  angles.forEach((ang, i) => {
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + R * Math.cos(ang), cy + R * Math.sin(ang));
    ctx.stroke();
    const label = byKey[RADAR_DIM_ORDER[i]]?.label || RADAR_DIM_ORDER[i];
    const lx = cx + (R + 14) * Math.cos(ang);
    const ly = cy + (R + 14) * Math.sin(ang);
    ctx.fillStyle = "rgba(180,180,180,0.8)";
    ctx.font = '10px -apple-system, sans-serif';
    ctx.textAlign = lx >= cx ? "left" : "right";
    ctx.fillText(String(label).split(" ")[0], lx, ly);
  });

  ctx.beginPath();
  angles.forEach((ang, i) => {
    const v = vals[i];
    const r = R * (0.15 + 0.85 * v);
    const x = cx + r * Math.cos(ang);
    const y = cy + r * Math.sin(ang);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
  ctx.fill();
  ctx.strokeStyle = "rgba(255, 255, 255, 0.5)";
  ctx.lineWidth = 1.5;
  ctx.stroke();

  ctx.fillStyle = "rgba(255, 255, 255, 0.4)";
  ctx.font = '10px -apple-system, sans-serif';
  ctx.textAlign = "center";
  ctx.fillText("magnitude → edge", cx, h - 14);
}

function prefersDualBrain3d() {
  return dualBrain3dEl?.checked === true;
}

function syncBrainDualLayout() {
  if (brainDualWrap) brainDualWrap.classList.toggle("is-single", !prefersDualBrain3d());
}

function summarizeVerticesForDebug(p) {
  if (!p || typeof p !== "object") return p;
  const o = { ...p };
  for (const k of ["vertex_delta_b64", "vertex_a_b64", "vertex_b_b64"]) {
    if (typeof o[k] === "string") o[k] = `[omitted ${o[k].length} base64 chars]`;
  }
  return o;
}

function stopLoadingExperience() {
  if (loadingFactsTimer != null) {
    clearInterval(loadingFactsTimer);
    loadingFactsTimer = null;
  }
  if (typeof loadingBrainDispose === "function") {
    loadingBrainDispose();
    loadingBrainDispose = null;
  }
}

function renderLoadingFactAt(facts, index, cardEl, sourceEl, dotsEl) {
  const f = facts[index];
  if (!cardEl || !f) return;
  cardEl.innerHTML =
    `<span class="loading-fact-tag">${escapeHtml(f.tag)}</span>` +
    `<h4 class="loading-fact-title">${escapeHtml(f.title)}</h4>` +
    `<p class="loading-fact-body">${escapeHtml(f.body)}</p>`;
  if (sourceEl) {
    if (f.source_url) {
      sourceEl.href = f.source_url;
      sourceEl.textContent = f.source_label || "Source";
      sourceEl.classList.remove("hidden");
    } else {
      sourceEl.classList.add("hidden");
    }
  }
  if (dotsEl) {
    dotsEl.querySelectorAll("button").forEach((b, j) => {
      const on = j === index;
      b.classList.toggle("loading-fact-dot-active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
  }
}

function startLoadingExperience() {
  stopLoadingExperience();

  const card = document.getElementById("loadingFactCard");
  const dots = document.getElementById("loadingFactDots");
  const source = document.getElementById("loadingFactSource");
  const canvas = document.getElementById("loadingBrainCanvas");

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (!reducedMotion && canvas && loadingEl && !loadingEl.classList.contains("hidden")) {
    import("./loadingBrain3d.js")
      .then((mod) => {
        if (loadingEl && !loadingEl.classList.contains("hidden")) {
          loadingBrainDispose = mod.mountLoadingBrainCanvas(canvas);
        }
      })
      .catch(() => {});
  }

  fetch(LOADING_FACTS_URL)
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      const facts = data?.facts;
      if (!Array.isArray(facts) || !facts.length) {
        if (card) {
          card.innerHTML =
            `<span class="loading-fact-tag">TRIBE v2</span>` +
            `<h4 class="loading-fact-title">Population-average cortex</h4>` +
            `<p class="loading-fact-body">Text is converted to speech-like timing, then TRIBE v2 estimates cortical activity you can compare between two drafts.</p>`;
        }
        if (source) source.classList.add("hidden");
        return;
      }

      const order = facts.map((_, i) => i);
      for (let i = order.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [order[i], order[j]] = [order[j], order[i]];
      }
      const orderedFacts = order.map((i) => facts[i]);
      let idx = 0;

      if (dots) {
        dots.innerHTML = orderedFacts
          .map(
            (_, j) =>
              `<button type="button" class="loading-fact-dot" role="tab" aria-selected="${j === 0}" aria-label="Note ${j + 1} of ${orderedFacts.length}"></button>`
          )
          .join("");
        dots.querySelectorAll("button").forEach((btn, j) => {
          btn.addEventListener("click", () => {
            idx = j;
            renderLoadingFactAt(orderedFacts, idx, card, source, dots);
          });
        });
      }

      renderLoadingFactAt(orderedFacts, idx, card, source, dots);

      loadingFactsTimer = window.setInterval(() => {
        idx = (idx + 1) % orderedFacts.length;
        renderLoadingFactAt(orderedFacts, idx, card, source, dots);
      }, reducedMotion ? 22000 : 8800);
    })
    .catch(() => {
      if (card) {
        card.innerHTML =
          `<span class="loading-fact-tag">Tip</span>` +
          `<h4 class="loading-fact-title">First run can be slow</h4>` +
          `<p class="loading-fact-body">Transcription and neural encoding are heavy on CPU. Later runs reuse warm caches.</p>`;
      }
      if (source) source.classList.add("hidden");
    });
}

function decodeVertexPlane(mod, payload, b64Key, listKey) {
  const fromB64 = mod.decodeVertexF32B64?.(payload[b64Key]);
  if (fromB64?.length === 20484) return fromB64;
  const list = payload[listKey];
  if (Array.isArray(list) && list.length === 20484) return Float32Array.from(list);
  return null;
}

async function refreshBrain3d(payload) {
  lastBrainPayload = payload;
  syncBrainDualLayout();
  try {
    const mod = await import("./brain3d.js");
    mod.disposeBrainViewer();
    const delta = decodeVertexPlane(mod, payload, "vertex_delta_b64", "vertex_delta");
    if (!delta || delta.length !== 20484) return;

    const mesh = await mod.fetchBrainMesh();
    const dual = prefersDualBrain3d();
    const a = decodeVertexPlane(mod, payload, "vertex_a_b64", "vertex_a");
    const b = decodeVertexPlane(mod, payload, "vertex_b_b64", "vertex_b");
    const wrapA = document.getElementById("brain3dWrapA");
    const wrapB = document.getElementById("brain3dWrapB");
    const tooltip = document.getElementById("brainTooltip");

    if (brainViewerLabelA) {
      brainViewerLabelA.textContent = dual ? "Version A" : "Cortical contrast (B − A)";
    }
    if (bwrLegendHint) {
      bwrLegendHint.textContent = dual
        ? "Each surface uses blue–white–red relative to that version’s median (same palette family as the static maps)."
        : "Blue–white–red shows signed contrast (B − A), matching the static difference figure below.";
    }

    if (dual && a && b && wrapA && wrapB) {
      const atlas = await mod.fetchVertexAtlas();
      mod.mountDualBrainViewer(wrapA, wrapB, a, b, mesh, atlas, tooltip);
      return;
    }

    const atlas = await mod.fetchVertexAtlas();
    if (wrapB) wrapB.innerHTML = "";
    if (wrapA) mod.mountBrainViewer(wrapA, delta, mesh, atlas, tooltip);
  } catch (err) {
    console.warn("brain3d fallback to PNG:", err);
  }
}

function renderBars(dimensions) {
  barsEl.innerHTML = "";
  (dimensions || []).forEach((row) => {
    const rowEl = document.createElement("div");
    rowEl.className = `bar-row ${row.low_confidence ? "low" : ""}`;
    rowEl.title = row.tooltip || "";
    rowEl.innerHTML = `
      <div class="bar-copy">
        <span class="bar-label">${escapeHtml(row.label)}</span>
        <span class="bar-meaning">${escapeHtml(row.meaning)}</span>
      </div>
      <div class="bar-track">
        <div class="bar-fill ${row.direction === "A_higher" ? "left" : "right"}" style="width:${Math.max(2, Math.round(row.bar_fraction * 100))}%"></div>
      </div>
      <div class="bar-meta">
        <span class="delta">${escapeHtml(row.delta_display)}</span>
        <span class="strength">${escapeHtml(row.winner)} · ${escapeHtml(row.strength)} · ${escapeHtml(row.confidence)}</span>
      </div>
    `;
    barsEl.appendChild(rowEl);
  });
}

function renderInsightList(targetEl, items, emptyText) {
  targetEl.innerHTML = "";
  if (!items || !items.length) {
    const card = document.createElement("div");
    card.className = "insight-card";
    card.innerHTML = `<p>${escapeHtml(emptyText)}</p>`;
    targetEl.appendChild(card);
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "insight-card";
    card.innerHTML = `
      <h4>${escapeHtml(item.title)}</h4>
      <p>${escapeHtml(item.body)}</p>
    `;
    targetEl.appendChild(card);
  });
}

function choreographReveal(payload, submittedA, submittedB) {
  const insights = payload.insights || {};
  headlineEl.textContent = insights.headline || payload.meta?.headline || "Brain Diff result";
  const ws = payload.meta?.winner_summary || { a_wins: 0, b_wins: 0, tied: 0 };
  winnerEl.textContent = `B wins on ${ws.b_wins} dimensions · A wins on ${ws.a_wins} · ${ws.tied} tied`;
  subheadEl.textContent = insights.subhead || "";
  renderMetricCards(insights.hero_metrics || []);
  renderBars(payload.dimensions || []);
  renderInsightList(whatChangedEl, insights.what_changed, "No major change emerged strongly enough to headline this run.");
  renderInsightList(whatStayedSimilarEl, insights.what_stayed_similar, "No dimensions were stable enough to call out here.");
  renderInsightList(actionablesEl, insights.actionables, "No actionable rewrite guidance available for this run.");
  coolFactorEl.textContent = insights.cool_factor || "";
  scientificNoteEl.textContent = insights.scientific_note || "";
  renderDimensionRadar(payload.dimensions || []);
  document.querySelectorAll("[data-brain-hemi]").forEach((b) => {
    b.classList.toggle("active", b.getAttribute("data-brain-hemi") === "both");
  });
  void refreshBrain3d(payload);
  if (atlasPeakLabel) {
    const peak = payload.meta?.atlas_peak;
    if (peak?.label) {
      atlasPeakLabel.classList.remove("hidden");
      atlasPeakLabel.textContent = `Strongest difference: ${peak.label} (${peak.hemisphere} hemisphere)`;
    } else {
      atlasPeakLabel.classList.add("hidden");
      atlasPeakLabel.textContent = "";
    }
  }
  if (payload.meta?.heatmap?.image_base64) {
    heatmapImg.src = `data:image/png;base64,${payload.meta.heatmap.image_base64}`;
  }
  resultJson.textContent = JSON.stringify(summarizeVerticesForDebug(payload), null, 2);

  resultEl.classList.remove("hidden");
  resultEl.querySelectorAll(".stage").forEach((el) => el.classList.remove("show"));
  [[".stage-1", 0], [".stage-2", 180], [".stage-3", 420], [".stage-4", 640], [".stage-5", 880]].forEach(([selector, delay]) => {
    setTimeout(() => {
      const node = resultEl.querySelector(selector);
      if (node) node.classList.add("show");
    }, delay);
  });
}


function formatMs(ms) {
  if (ms == null || Number.isNaN(Number(ms))) return "—";
  const n = Number(ms);
  if (n < 1000) return `${Math.round(n)} ms`;
  return `${(n / 1000).toFixed(2)} s`;
}

function openDiagnostics() {
  diagDrawer?.classList.remove("hidden");
  diagBackdrop?.classList.remove("hidden");
  diagDrawer?.setAttribute("aria-hidden", "false");
}

function closeDiagnostics() {
  diagDrawer?.classList.add("hidden");
  diagBackdrop?.classList.add("hidden");
  diagDrawer?.setAttribute("aria-hidden", "true");
}

function renderKV(target, rows) {
  if (!target) return;
  target.innerHTML = "";
  rows.forEach(([k, v]) => {
    const row = document.createElement("div");
    row.className = "kv-row";
    row.innerHTML = `<span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(String(v ?? "—"))}</span>`;
    target.appendChild(row);
  });
}

function _runtimeLabel(report) {
  const backend = report?.runtime?.backend;
  const device = report?.runtime?.device;
  const strategy = report?.text_backend_strategy;
  if (!backend) return "unknown";
  let label = `${backend} · ${device}`;
  if (backend === "mps" && strategy === "mps_split") {
    label += " — Apple Silicon: MPS for brain path, CPU for Whisper transcription";
  } else if (strategy === "cpu") {
    label += " — CPU compatibility path (slower)";
  }
  return label;
}

function renderPreflightDiagnostics(report) {
  if (!preflightStatus || !preflightList) return;
  preflightStatus.textContent = report?.ok ? "Ready" : "Needs attention";
  preflightStatus.className = `status-pill ${report?.ok ? "ok" : "error"}`;
  const rows = [
    ["Model", report?.model_loaded ? "loaded" : "not loaded"],
    ["Masks", report?.masks_ready ? "ready" : "not ready"],
    ["FFmpeg", report?.ffmpeg?.detail || (report?.ffmpeg?.ok ? "ok" : "missing")],
    ["uvx", report?.uvx?.detail || (report?.uvx?.ok ? "ok" : "missing")],
    ["HF access", report?.hf_gated_model_access?.detail || (report?.hf_gated_model_access?.ok ? "ok" : "missing")],
    ["Runtime", _runtimeLabel(report)],
    ["Text backend", report?.text_backend_strategy || "unknown"],
    ["Hard timeout", report?.limits?.hard_timeout_ms ? `${(report.limits.hard_timeout_ms / 1000).toFixed(0)} s` : "—"],
  ];
  if (report?.blockers?.length) rows.push(["Blockers", report.blockers.join(", ")]);
  renderKV(preflightList, rows);
}

function renderCurrentRun(run, source = "result") {
  if (!currentRunStatus || !currentRunPanel) return;
  const stage = run?.status || (run?.success ? "done" : "unknown");
  currentRunStatus.textContent = source === "result" ? `Current · ${stage}` : `Stored · ${stage}`;
  currentRunStatus.className = `status-pill ${stage === "done" || run?.success ? "ok" : stage === "error" ? "error" : "pending"}`;
  const runtime = run?.runtime || {};
  const stageTimes = run?.stage_times || run?.meta?.stage_times || {};
  const rows = [
    ["Total", formatMs(run?.total_ms ?? run?.meta?.processing_time_ms)],
    ["A events", formatMs(stageTimes.text_a_event_ms ?? stageTimes.events_a_ms)],
    ["A predict", formatMs(stageTimes.text_a_predict_ms ?? stageTimes.predict_a_ms)],
    ["B events", formatMs(stageTimes.text_b_event_ms ?? stageTimes.events_b_ms)],
    ["B predict", formatMs(stageTimes.text_b_predict_ms ?? stageTimes.predict_b_ms)],
    ["Score/diff", formatMs(stageTimes.score_diff_ms)],
    ["Heatmap", formatMs(stageTimes.heatmap_ms)],
    ["Runtime", runtime.backend ? `${runtime.backend} · ${runtime.device}` : (preflightState?.runtime?.backend ? `${preflightState.runtime.backend} · ${preflightState.runtime.device}` : "unknown")],
    ["Timesteps", `${run?.text_a_timesteps ?? run?.meta?.text_a_timesteps ?? 0} / ${run?.text_b_timesteps ?? run?.meta?.text_b_timesteps ?? 0}`],
  ];
  if (run?.warnings?.length || run?.meta?.warnings?.length) rows.push(["Warnings", (run.warnings || run.meta.warnings).join(" | ")]);
  if (run?.error_message) rows.push(["Error", run.error_message]);
  renderKV(currentRunPanel, rows);
}

async function fetchRecentTelemetry() {
  if (!recentRuns) return;
  try {
    const res = await fetch("/api/telemetry/recent?limit=8");
    if (!res.ok) throw new Error("Unable to fetch telemetry");
    const payload = await res.json();
    const runs = payload.runs || [];
    if (!runs.length) {
      recentRuns.className = "recent-runs empty";
      recentRuns.textContent = "No runs recorded yet.";
      return;
    }
    recentRuns.className = "recent-runs";
    recentRuns.innerHTML = "";
    runs.forEach((run) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "run-card";
      card.innerHTML = `<div class="run-card-title"><span>${escapeHtml(run.created_at || "Run")}</span><span>${escapeHtml(formatMs(run.total_ms))}</span></div><div class="run-card-meta">${escapeHtml((run.runtime?.backend ? `${run.runtime.backend} · ${run.runtime.device}` : "runtime unknown"))} · ${escapeHtml(run.success ? "success" : "error")}</div>`;
      card.addEventListener("click", async () => {
        try {
          const res = await fetch(`/api/telemetry/run/${run.job_id}`);
          if (!res.ok) throw new Error();
          const full = await res.json();
          renderCurrentRun(full, "telemetry");
        } catch {
          renderCurrentRun(run, "telemetry");
        }
        openDiagnostics();
      });
      recentRuns.appendChild(card);
    });
  } catch {
    recentRuns.className = "recent-runs empty";
    recentRuns.textContent = "Unable to load telemetry.";
  }
}

async function fetchApiReady() {
  if (!apiReadyPill) return;
  try {
    const res = await fetch("/api/ready");
    if (!res.ok) throw new Error("ready");
    const j = await res.json();
    if (j.startup_skipped) {
      apiReadyPill.textContent = "Startup skipped";
      apiReadyPill.title = "BRAIN_DIFF_SKIP_STARTUP=1 — models not loaded in this process";
      apiReadyPill.className = "api-ready-pill warn";
      return;
    }
    const ok = j.ok && j.model_loaded && j.masks_ready;
    apiReadyPill.textContent = ok ? "Models ready" : "Not ready";
    apiReadyPill.title = "";
    apiReadyPill.className = `api-ready-pill ${ok ? "ok" : "error"}`;
    if (j.warmup_requested && !j.warmup_completed && j.warmup_error) {
      apiReadyPill.textContent = "Warmup issue";
      apiReadyPill.title = j.warmup_error;
    }
  } catch {
    apiReadyPill.textContent = "API offline";
    apiReadyPill.className = "api-ready-pill error";
  }
}

async function fetchPreflight() {
  try {
    const res = await fetch("/api/preflight");
    if (!res.ok) throw new Error(`preflight ${res.status}`);
    preflightState = await res.json();
    renderPreflightDiagnostics(preflightState);
    if (!preflightState.ok) {
      const issues = [...(preflightState.errors || []), ...(preflightState.warnings || []), ...(preflightState.blockers || [])].join(" · ");
      ctaNote.textContent = issues || "System not ready yet.";
      if (runMeta) runMeta.textContent = "Diagnostics will unlock compare once the local runtime is ready.";
    } else {
      ctaNote.textContent = "TRIBEv2 ready. Text is processed through speech timing before cortical contrast is computed.";
      if (runMeta) runMeta.textContent = "Ready. Diagnostics stay tucked away until you need them.";
    }
  } catch {
    preflightState = { ok: false, blockers: [], errors: ["Unable to reach local API preflight"] };
    ctaNote.textContent = "Unable to verify local model readiness. Start the API first.";
  }
  updateFormState();
}

async function pollStatus(jobId) {
  const started = performance.now();
  const slowNoticeMs = preflightState?.limits?.slow_notice_ms ?? DEFAULT_SLOW_NOTICE_MS;
  const hardTimeoutMs = preflightState?.limits?.hard_timeout_ms ?? DEFAULT_HARD_TIMEOUT_MS;
  let slowNoticeFired = false;
  let seenEventCount = 0;

  while (true) {
    const elapsed = performance.now() - started;

    if (elapsed > hardTimeoutMs) {
      throw new Error(
        `Run exceeded ${(hardTimeoutMs / 1000).toFixed(0)} s hard timeout. Check server logs.`
      );
    }

    const res = await fetch(`/api/diff/status/${jobId}`);
    if (!res.ok) throw new Error(`Status request failed (${res.status})`);
    const payload = await res.json();

    if (loadingTelemetry) {
      loadingTelemetry.classList.remove("hidden");
      loadingTelemetry.innerHTML = `<strong>Live timing</strong><div>Total elapsed: ${formatMs(elapsed)}</div>`;
    }

    // Only process new events since last poll.
    const allEvents = payload.events || [];
    const newEvents = allEvents.slice(seenEventCount);
    seenEventCount = allEvents.length;

    newEvents.forEach((event) => {
      if (event.status === "slow_processing") {
        loadingHintEl.textContent = "Still processing — this run is taking longer than expected.";
      } else {
        markLoadingStep(event.status);
      }
    });

    if (!slowNoticeFired && elapsed > slowNoticeMs) {
      slowNoticeFired = true;
      loadingHintEl.textContent =
        "This is taking a while — on CPU or MPS that is normal for the first run. Hang tight.";
    }

    if (payload.status === "done") return payload.result;
    if (payload.status === "error") throw new Error(formatJobError(payload.error));
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

async function runDiff() {
  if (isSubmitting || !textA.value.trim() || !textB.value.trim()) return;
  if (preflightState && !preflightState.ok) {
    loadingHintEl.textContent = "Fix preflight issues before running Brain Diff.";
    return;
  }
  isSubmitting = true;
  updateFormState();
  landingEl.classList.add("hidden");
  resultEl.classList.add("hidden");
  loadingEl.classList.remove("hidden");
  resetLoadingSteps();
  startLoadingExperience();
  const submittedA = textA.value;
  const submittedB = textB.value;

  try {
    const startRes = await fetch("/api/diff/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text_a: submittedA, text_b: submittedB })
    });
    if (!startRes.ok) throw new Error(`Start request failed (${startRes.status})`);
    const start = await startRes.json();
    const result = await pollStatus(start.job_id);
    stopLoadingExperience();
    loadingEl.classList.add("hidden");
    landingEl.classList.remove("hidden");
    choreographReveal(result, submittedA, submittedB);
    renderCurrentRun({ ...result.meta, ...{ status: "done", warnings: result.warnings, runtime: preflightState?.runtime || {}, stage_times: result.meta?.stage_times || {} } }, "result");
    fetchRecentTelemetry();
    latestShareData = { result, textA: submittedA, textB: submittedB };
  } catch (err) {
    loadingHintEl.textContent = `Something went wrong: ${err.message}`;
    retryBtn.classList.remove("hidden");
  } finally {
    stopLoadingExperience();
    isSubmitting = false;
    updateFormState();
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Unable to load heatmap image"));
    img.src = src;
  });
}

function drawWrappedText(ctx, text, x, y, maxWidth, lineHeight, maxLines) {
  const words = String(text || "").split(/\s+/);
  const lines = [];
  let current = "";
  words.forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (ctx.measureText(candidate).width <= maxWidth) current = candidate;
    else {
      if (current) lines.push(current);
      current = word;
    }
  });
  if (current) lines.push(current);
  const clipped = lines.slice(0, maxLines);
  if (lines.length > maxLines && clipped.length) clipped[clipped.length - 1] = `${clipped[clipped.length - 1].replace(/\.+$/, "")}…`;
  clipped.forEach((line, idx) => ctx.fillText(line, x, y + idx * lineHeight));
}

async function buildShareImageBlob() {
  if (!latestShareData?.result || !heatmapImg.src) throw new Error("No result available to share yet");
  const { result, textA: submittedA, textB: submittedB } = latestShareData;
  const canvas = document.createElement("canvas");
  canvas.width = 1320;
  canvas.height = 760;
  const ctx = canvas.getContext("2d");

  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.fillStyle = "#666666";
  ctx.font = '14px -apple-system, sans-serif';
  ctx.fillText("BRAIN DIFF", 54, 52);
  ctx.fillStyle = "#ffffff";
  ctx.font = 'bold 48px -apple-system, sans-serif';
  drawWrappedText(ctx, result.insights?.headline || result.meta?.headline || "Brain Diff", 54, 112, 650, 52, 3);
  ctx.fillStyle = "#999999";
  ctx.font = '20px -apple-system, sans-serif';
  drawWrappedText(ctx, result.insights?.subhead || "", 54, 248, 650, 28, 3);

  const topDims = (result.dimensions || []).slice(0, 2);
  if (topDims.length) {
    ctx.fillStyle = "#666666";
    ctx.font = '13px -apple-system, sans-serif';
    ctx.fillText(`${topDims.map((r) => `${r.label} (${r.winner})`).join(" · ")}`, 54, 310);
  }

  function panel(x, y, w, h) {
    ctx.fillStyle = "rgba(15,15,15,0.9)";
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    const r = 22;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }

  panel(54, 350, 620, 124);
  panel(54, 490, 620, 124);
  panel(706, 350, 560, 264);

  ctx.fillStyle = "#666666";
  ctx.font = '12px -apple-system, sans-serif';
  ctx.fillText("VERSION A", 74, 378);
  ctx.fillText("VERSION B", 74, 518);
  ctx.fillStyle = "#dddddd";
  ctx.font = '22px -apple-system, sans-serif';
  drawWrappedText(ctx, truncate(submittedA, 160), 74, 408, 582, 28, 2);
  drawWrappedText(ctx, truncate(submittedB, 160), 74, 548, 582, 28, 2);

  const bars = (result.dimensions || []).slice(0, 3);
  const maxAbs = Math.max(0.0001, ...bars.map((row) => Math.abs(Number(row.delta || 0))));
  ctx.fillStyle = "#666666";
  ctx.font = '12px -apple-system, sans-serif';
  ctx.fillText("TOP CONTRASTS", 726, 378);
  bars.forEach((row, idx) => {
    const y = 410 + idx * 72;
    ctx.fillStyle = "#ffffff";
    ctx.font = '16px -apple-system, sans-serif';
    ctx.fillText(row.label, 726, y);
    ctx.fillStyle = "rgba(255,255,255,0.06)";
    ctx.fillRect(726, y + 16, 480, 12);
    ctx.fillStyle = Math.sign(Number(row.delta || 0)) >= 0 ? "#5ac8b8" : "#e8665a";
    const width = Math.max(12, Math.round((Math.abs(Number(row.delta || 0)) / maxAbs) * 240));
    ctx.fillRect(Math.sign(Number(row.delta || 0)) >= 0 ? 966 : 966 - width, y + 16, width, 12);
    ctx.fillStyle = "#777777";
    ctx.font = '11px -apple-system, sans-serif';
    ctx.fillText(`${row.winner} · ${row.strength}`, 726, y + 48);
  });
  ctx.fillStyle = "rgba(255,255,255,0.08)";
  ctx.fillRect(965, 420, 1, 160);

  const heatmap = await loadImage(heatmapImg.src);
  panel(706, 626, 560, 104);
  ctx.drawImage(heatmap, 718, 638, 536, 80);

  ctx.fillStyle = "#555555";
  ctx.font = '11px -apple-system, sans-serif';
  ctx.fillText(`model:${String(result.meta?.model_revision || "unknown").slice(0, 30)}`, 54, 710);
  ctx.fillText(`atlas:${String(result.meta?.atlas || "unknown")}`, 430, 710);
  ctx.fillText("braindiff.xyz", 1135, 710);

  return await new Promise((resolve, reject) => {
    canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Unable to encode share image")), "image/png");
  });
}

function initHeroStage() {
  if (!heroCanvas) return;
  const ctx = heroCanvas.getContext("2d");
  const DPR = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
  let particles = [];
  let raf = null;

  function resize() {
    const rect = heroCanvas.getBoundingClientRect();
    heroCanvas.width = rect.width * DPR;
    heroCanvas.height = rect.height * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const count = Math.max(42, Math.min(96, Math.floor(rect.width / 8)));
    particles = Array.from({ length: count }, (_, i) => ({
      x: Math.random() * rect.width,
      y: Math.random() * rect.height,
      r: Math.random() * 2 + 0.7,
      vx: (Math.random() - 0.5) * 0.16,
      vy: (Math.random() - 0.5) * 0.16,
      a: Math.random() * Math.PI * 2,
      hue: i % 3
    }));
  }

  function draw(t) {
    const { width, height } = heroCanvas.getBoundingClientRect();
    ctx.clearRect(0, 0, width, height);

    particles.forEach((p, idx) => {
      p.x += p.vx + Math.sin((t / 1400) + p.a) * 0.02;
      p.y += p.vy + Math.cos((t / 1600) + p.a) * 0.02;
      if (p.x < -20) p.x = width + 20;
      if (p.x > width + 20) p.x = -20;
      if (p.y < -20) p.y = height + 20;
      if (p.y > height + 20) p.y = -20;

      for (let j = idx + 1; j < particles.length; j += 1) {
        const q = particles[j];
        const dx = p.x - q.x;
        const dy = p.y - q.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 80) {
          const alpha = 0.08 * (1 - dist / 80);
          ctx.strokeStyle = `rgba(255, 255, 255, ${alpha})`;
          ctx.lineWidth = 0.5;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.stroke();
        }
      }

      const alpha = 0.3 + 0.3 * Math.sin(t / 2000 + p.a);
      ctx.fillStyle = `rgba(255, 255, 255, ${alpha})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    });

    raf = requestAnimationFrame(draw);
  }

  resize();
  cancelAnimationFrame(raf);
  raf = requestAnimationFrame(draw);
  window.addEventListener("resize", resize, { passive: true });
}

textA.addEventListener("input", updateFormState);
textB.addEventListener("input", updateFormState);
runBtn.addEventListener("click", runDiff);
retryBtn.addEventListener("click", runDiff);
shareBtn.addEventListener("click", () => {
  buildShareImageBlob()
    .then(async (blob) => {
      try {
        await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
        shareBtn.textContent = "Copied share image";
      } catch {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "brain-diff-share.png";
        a.click();
        URL.revokeObjectURL(url);
        shareBtn.textContent = "Downloaded share image";
      }
      setTimeout(() => { shareBtn.textContent = "Share"; }, 1800);
    })
    .catch((err) => {
      shareBtn.textContent = err.message || "Share failed";
      setTimeout(() => { shareBtn.textContent = "Share"; }, 1800);
    });
});
diagToggle?.addEventListener("click", openDiagnostics);
diagClose?.addEventListener("click", closeDiagnostics);
diagBackdrop?.addEventListener("click", closeDiagnostics);
diagRefresh?.addEventListener("click", fetchRecentTelemetry);
diagShortcut?.addEventListener("click", openDiagnostics);

exampleBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    textA.value = btn.dataset.a || "";
    textB.value = btn.dataset.b || "";
    updateFormState();
  });
});

document.querySelectorAll("[data-brain-hemi]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const mode = btn.getAttribute("data-brain-hemi");
    if (!mode) return;
    try {
      const mod = await import("./brain3d.js");
      mod.setBrainHemisphere(mode);
    } catch {
      /* viewer not loaded yet */
    }
    document.querySelectorAll("[data-brain-hemi]").forEach((b) => {
      b.classList.toggle("active", b === btn);
    });
  });
});

if (dualBrain3dEl) {
  dualBrain3dEl.checked = localStorage.getItem(DUAL_3D_STORAGE_KEY) === "1";
  syncBrainDualLayout();
  dualBrain3dEl.addEventListener("change", () => {
    localStorage.setItem(DUAL_3D_STORAGE_KEY, dualBrain3dEl.checked ? "1" : "0");
    syncBrainDualLayout();
    if (lastBrainPayload) void refreshBrain3d(lastBrainPayload);
    else if (bwrLegendHint) {
      bwrLegendHint.textContent = dualBrain3dEl.checked
        ? "Each surface uses blue–white–red relative to that version’s median (same palette family as the static maps)."
        : "Blue–white–red shows signed contrast (B − A), matching the static difference figure below.";
    }
  });
}

initHeroStage();
fetchPreflight();
fetchApiReady();
fetchRecentTelemetry();
updateFormState();
