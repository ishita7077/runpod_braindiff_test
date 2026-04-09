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
const snapshotAEl = document.getElementById("snapshotA");
const snapshotBEl = document.getElementById("snapshotB");
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

let isSubmitting = false;
let preflightState = null;
let latestShareData = null;

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
  const preflightOk = preflightState ? !!preflightState.ok : true;
  runBtn.disabled = !hasContent || !preflightOk || isSubmitting;
}

function formatJobError(errorPayload) {
  const code = errorPayload?.code;
  if (code === "HF_AUTH_REQUIRED") return "Model access required. Authenticate HuggingFace for the gated text encoder.";
  if (code === "FFMPEG_REQUIRED") return "ffmpeg is missing for text-to-speech transcription.";
  if (code === "UVX_REQUIRED") return "uv/uvx is missing (needed for WhisperX transcription). Install uv in your venv.";
  if (code === "WHISPERX_FAILED")
    return "Transcription (WhisperX) failed. On Mac, Whisper uses CPU; check logs or try a smaller TRIBEV2_WHISPERX_MODEL.";
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
  snapshotAEl.textContent = truncate(submittedA, 210);
  snapshotBEl.textContent = truncate(submittedB, 210);
  renderMetricCards(insights.hero_metrics || []);
  renderBars(payload.dimensions || []);
  renderInsightList(whatChangedEl, insights.what_changed, "No major change emerged strongly enough to headline this run.");
  renderInsightList(whatStayedSimilarEl, insights.what_stayed_similar, "No dimensions were stable enough to call out here.");
  renderInsightList(actionablesEl, insights.actionables, "No actionable rewrite guidance available for this run.");
  coolFactorEl.textContent = insights.cool_factor || "";
  scientificNoteEl.textContent = insights.scientific_note || "";
  if (payload.meta?.heatmap?.image_base64) {
    heatmapImg.src = `data:image/png;base64,${payload.meta.heatmap.image_base64}`;
  }
  resultJson.textContent = JSON.stringify(payload, null, 2);

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
    ["Runtime", report?.runtime?.backend ? `${report.runtime.backend} · ${report.runtime.device}` : "unknown"],
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
    preflightState = { ok: false, errors: ["Unable to reach local API preflight"] };
    ctaNote.textContent = "Unable to verify local model readiness. Start the API first.";
  }
  updateFormState();
}

async function pollStatus(jobId) {
  const started = performance.now();
  while (true) {
    if (performance.now() - started > 180000) {
      throw new Error("Run exceeded 180s. This system likely needs diagnostics / acceleration.");
    }
    const res = await fetch(`/api/diff/status/${jobId}`);
    if (!res.ok) throw new Error(`Status request failed (${res.status})`);
    const payload = await res.json();
    (payload.events || []).forEach((event) => {
      if (loadingTelemetry) {
        const elapsed = performance.now() - started;
        loadingTelemetry.classList.remove("hidden");
        loadingTelemetry.innerHTML = `<strong>Live timing</strong><div>Total elapsed: ${formatMs(elapsed)}</div>`;
      }
      if (event.status === "slow_processing") {
        loadingHintEl.textContent = "Still processing — this run is taking longer than expected.";
      } else {
        markLoadingStep(event.status);
      }
    });
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

  const bg = ctx.createLinearGradient(0, 0, 0, canvas.height);
  bg.addColorStop(0, "#050812");
  bg.addColorStop(1, "#08111d");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const auraA = ctx.createRadialGradient(180, 110, 10, 180, 110, 330);
  auraA.addColorStop(0, "rgba(45,212,191,0.20)");
  auraA.addColorStop(1, "rgba(45,212,191,0)");
  ctx.fillStyle = auraA;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const auraB = ctx.createRadialGradient(1080, 120, 10, 1080, 120, 280);
  auraB.addColorStop(0, "rgba(125,211,252,0.14)");
  auraB.addColorStop(1, "rgba(125,211,252,0)");
  ctx.fillStyle = auraB;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.fillStyle = "#94a3b8";
  ctx.font = '16px "IBM Plex Mono", monospace';
  ctx.fillText("BRAIN DIFF", 54, 52);
  ctx.fillStyle = "#f8fafc";
  ctx.font = 'bold 52px "Iowan Old Style", serif';
  drawWrappedText(ctx, result.insights?.headline || result.meta?.headline || "Brain Diff", 54, 118, 650, 54, 3);
  ctx.fillStyle = "#dbe7f6";
  ctx.font = '22px "Iowan Old Style", serif';
  drawWrappedText(ctx, result.insights?.subhead || "", 54, 254, 650, 30, 3);

  function panel(x, y, w, h) {
    ctx.fillStyle = "rgba(11,17,31,0.84)";
    ctx.strokeStyle = "rgba(148,163,184,0.14)";
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

  ctx.fillStyle = "#7dd3fc";
  ctx.font = '13px "IBM Plex Mono", monospace';
  ctx.fillText("VERSION A", 74, 378);
  ctx.fillText("VERSION B", 74, 518);
  ctx.fillStyle = "#eef2ff";
  ctx.font = '24px "Iowan Old Style", serif';
  drawWrappedText(ctx, truncate(submittedA, 160), 74, 414, 582, 30, 2);
  drawWrappedText(ctx, truncate(submittedB, 160), 74, 554, 582, 30, 2);

  const bars = (result.dimensions || []).slice(0, 3);
  const maxAbs = Math.max(0.0001, ...bars.map((row) => Math.abs(Number(row.delta || 0))));
  ctx.fillStyle = "#cbd5e1";
  ctx.font = '13px "IBM Plex Mono", monospace';
  ctx.fillText("TOP CONTRASTS", 726, 378);
  bars.forEach((row, idx) => {
    const y = 410 + idx * 72;
    ctx.fillStyle = "#f8fafc";
    ctx.font = '18px "Iowan Old Style", serif';
    ctx.fillText(row.label, 726, y);
    ctx.fillStyle = "rgba(23,33,50,1)";
    ctx.fillRect(726, y + 18, 480, 14);
    ctx.fillStyle = Math.sign(Number(row.delta || 0)) >= 0 ? "#2dd4bf" : "#fb7185";
    const width = Math.max(12, Math.round((Math.abs(Number(row.delta || 0)) / maxAbs) * 240));
    ctx.fillRect(Math.sign(Number(row.delta || 0)) >= 0 ? 966 : 966 - width, y + 18, width, 14);
    ctx.fillStyle = "#94a3b8";
    ctx.font = '12px "IBM Plex Mono", monospace';
    ctx.fillText(`${row.winner} · ${row.strength}`, 726, y + 52);
  });
  ctx.fillStyle = "rgba(255,255,255,0.12)";
  ctx.fillRect(965, 420, 2, 160);

  const heatmap = await loadImage(heatmapImg.src);
  panel(706, 626, 560, 104);
  ctx.drawImage(heatmap, 718, 638, 536, 80);

  ctx.fillStyle = "#9ca3af";
  ctx.font = '12px "IBM Plex Mono", monospace';
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

    const g = ctx.createLinearGradient(0, 0, width, height);
    g.addColorStop(0, "rgba(8,14,25,0.18)");
    g.addColorStop(1, "rgba(5,9,18,0.0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, width, height);

    particles.forEach((p, idx) => {
      p.x += p.vx + Math.sin((t / 1200) + p.a) * 0.03;
      p.y += p.vy + Math.cos((t / 1400) + p.a) * 0.03;
      if (p.x < -20) p.x = width + 20;
      if (p.x > width + 20) p.x = -20;
      if (p.y < -20) p.y = height + 20;
      if (p.y > height + 20) p.y = -20;

      for (let j = idx + 1; j < particles.length; j += 1) {
        const q = particles[j];
        const dx = p.x - q.x;
        const dy = p.y - q.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 84) {
          ctx.strokeStyle = `rgba(${p.hue === 0 ? "125,211,252" : p.hue === 1 ? "45,212,191" : "251,113,133"}, ${0.14 * (1 - dist / 84)})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.stroke();
        }
      }

      const color = p.hue === 0 ? "125,211,252" : p.hue === 1 ? "45,212,191" : "251,113,133";
      ctx.fillStyle = `rgba(${color},0.9)`;
      ctx.shadowColor = `rgba(${color},0.45)`;
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
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

initHeroStage();
fetchPreflight();
fetchRecentTelemetry();
updateFormState();
