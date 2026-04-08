const textA = document.getElementById("textA");
const textB = document.getElementById("textB");
const countA = document.getElementById("countA");
const countB = document.getElementById("countB");
const runBtn = document.getElementById("runBtn");
const loadingEl = document.getElementById("loading");
const landingEl = document.getElementById("landing");
const loadingHintEl = document.getElementById("loadingHint");
const resultEl = document.getElementById("result");
const resultJson = document.getElementById("resultJson");
const headlineEl = document.getElementById("headline");
const winnerEl = document.getElementById("winner");
const barsEl = document.getElementById("bars");
const heatmapImg = document.getElementById("heatmapImg");
const explanationEl = document.getElementById("explanation");
const shareBtn = document.getElementById("shareBtn");
const retryBtn = document.getElementById("retryBtn");
const loadingSteps = document.getElementById("loadingSteps");
const exampleBtns = document.querySelectorAll(".example");
let isSubmitting = false;
let latestShareData = null;

function formatJobError(errorPayload) {
  const code = errorPayload?.code;
  if (code === "HF_AUTH_REQUIRED") {
    return "Model access required. Authenticate HuggingFace for meta-llama/Llama-3.2-3B.";
  }
  if (code === "FFMPEG_REQUIRED") {
    return "ffmpeg is missing for text-to-speech transcription.";
  }
  if (code === "ATLAS_MAPPING_ERROR") {
    return "Atlas mapping failed. Check HCP atlas files and labels.";
  }
  return errorPayload?.message || "Diff job failed";
}

function updateFormState() {
  countA.textContent = `${textA.value.length} / 5000`;
  countB.textContent = `${textB.value.length} / 5000`;
  runBtn.disabled = !textA.value.trim() || !textB.value.trim();
  autoResize(textA);
  autoResize(textB);
}

function autoResize(el) {
  el.style.height = "auto";
  el.style.height = `${Math.min(el.scrollHeight, 300)}px`;
}

function truncateForShare(text, maxChars = 60) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) return normalized;
  return `${normalized.slice(0, maxChars - 3)}...`;
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Unable to load heatmap image"));
    img.src = src;
  });
}

function drawCenteredWrappedText(ctx, text, x, y, maxWidth, lineHeight, maxLines) {
  const words = text.split(/\s+/);
  const lines = [];
  let current = "";
  words.forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (ctx.measureText(candidate).width <= maxWidth) {
      current = candidate;
      return;
    }
    if (current) lines.push(current);
    current = word;
  });
  if (current) lines.push(current);
  const sliced = lines.slice(0, maxLines);
  if (lines.length > maxLines && sliced.length > 0) {
    const lastIdx = sliced.length - 1;
    sliced[lastIdx] = `${sliced[lastIdx].replace(/\.+$/, "")}...`;
  }
  sliced.forEach((line, idx) => {
    ctx.fillText(line, x, y + idx * lineHeight);
  });
}

function markLoadingStep(status) {
  const target = loadingSteps.querySelector(`[data-step="${status}"]`);
  if (!target) return;
  target.classList.add("done");
  target.textContent = `✓ ${target.textContent.replace(/^✓\s*/, "")}`;
}

function resetLoadingSteps() {
  loadingSteps.querySelectorAll("li").forEach((li) => {
    li.classList.remove("done");
    li.textContent = li.textContent.replace(/^✓\s*/, "");
  });
  loadingHintEl.textContent = "";
  retryBtn.classList.add("hidden");
}

function buildNarrative(payload) {
  const strongest = payload.dimensions?.[0];
  if (!strongest) {
    return "Differences shown are normalized signed contrasts across the five dimensions.";
  }
  const impactMap = {
    personal_resonance: "self-relevance and message value",
    social_thinking: "how much people reason about others",
    brain_effort: "cognitive effort during interpretation",
    language_depth: "deep language processing",
    gut_reaction: "visceral emotional salience",
  };
  const outcomeMap = {
    personal_resonance: "real-world behavior change",
    social_thinking: "changes in social decision-making",
    brain_effort: "comprehension and deliberation outcomes",
    language_depth: "memory and semantic integration outcomes",
    gut_reaction: "affective response and behavior",
  };
  const direction = strongest.direction === "B_higher" ? "Version B" : strongest.direction === "A_higher" ? "Version A" : "Both versions";
  const pct = Math.abs(strongest.delta) * 100;
  return `${direction} activates ${strongest.label} ${pct.toFixed(1)}% more strongly. Content engaging this pattern tends to increase ${impactMap[strongest.key]}. Higher activation here was linked to ${outcomeMap[strongest.key]} (Falk et al., 2012).`;
}

function renderBars(dimensions) {
  barsEl.innerHTML = "";
  dimensions.forEach((row) => {
    const rowEl = document.createElement("div");
    rowEl.className = `bar-row ${row.low_confidence ? "low" : ""}`;
    rowEl.title = row.tooltip;

    const label = document.createElement("div");
    label.textContent = row.label;

    const track = document.createElement("div");
    track.className = "bar-track";

    const fill = document.createElement("div");
    fill.className = `bar-fill ${row.direction === "A_higher" ? "left" : "right"}`;
    fill.style.width = `${Math.max(2, Math.round(row.bar_fraction * 100))}%`;
    track.appendChild(fill);

    const delta = document.createElement("div");
    delta.className = "delta";
    const arrow = row.direction === "A_higher" ? "←" : row.direction === "B_higher" ? "→" : "·";
    delta.textContent = `${row.delta_display} ${arrow}`;

    rowEl.appendChild(label);
    rowEl.appendChild(track);
    rowEl.appendChild(delta);
    barsEl.appendChild(rowEl);
  });
}

function choreographReveal(payload) {
  resultEl.classList.remove("hidden");
  resultEl.querySelectorAll(".stage").forEach((el) => el.classList.remove("show"));

  headlineEl.textContent = payload.meta.headline;
  const ws = payload.meta.winner_summary;
  winnerEl.textContent = `B wins on ${ws.b_wins} dimensions · A wins on ${ws.a_wins} · ${ws.tied} tied`;
  renderBars(payload.dimensions);
  const notes = payload.warnings.length > 0 ? ` Notes: ${payload.warnings.join(" | ")}.` : "";
  explanationEl.textContent = `${buildNarrative(payload)}${notes}`;
  if (payload.meta.heatmap?.image_base64) {
    heatmapImg.src = `data:image/png;base64,${payload.meta.heatmap.image_base64}`;
  }

  const stageDelays = [
    [".stage-1", 0],
    [".stage-2", 300],
    [".stage-3", 600],
    [".stage-4", 1200],
    [".stage-5", 1500],
    [".stage-6", 2000],
  ];
  stageDelays.forEach(([selector, delay]) => {
    setTimeout(() => {
      const node = resultEl.querySelector(selector);
      if (node) node.classList.add("show");
    }, delay);
  });
}

async function buildShareImageBlob() {
  if (!latestShareData?.result || !heatmapImg.src) {
    throw new Error("No result available to share yet");
  }
  const { result, textA: submittedA, textB: submittedB } = latestShareData;
  const canvas = document.createElement("canvas");
  canvas.width = 1200;
  canvas.height = 675;
  const ctx = canvas.getContext("2d");

  ctx.fillStyle = "#0f1116";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  ctx.fillStyle = "#9ca3af";
  ctx.font = '18px "IBM Plex Mono", monospace';
  ctx.textAlign = "left";
  ctx.fillText("BRAIN DIFF", 48, 50);

  ctx.fillStyle = "#f3f4f6";
  ctx.font = 'bold 44px "Iowan Old Style", serif';
  ctx.textAlign = "center";
  drawCenteredWrappedText(ctx, result.meta.headline || "Brain response contrast", 600, 92, 760, 52, 2);

  const textAreaX = 48;
  const textAreaW = 660;
  ctx.fillStyle = "#151924";
  ctx.fillRect(textAreaX, 178, textAreaW, 110);
  ctx.fillRect(textAreaX, 300, textAreaW, 110);

  ctx.fillStyle = "#93c5fd";
  ctx.font = '16px "IBM Plex Mono", monospace';
  ctx.textAlign = "left";
  ctx.fillText("Version A", textAreaX + 16, 202);
  ctx.fillText("Version B", textAreaX + 16, 324);

  ctx.fillStyle = "#f3f4f6";
  ctx.font = '22px "Iowan Old Style", serif';
  ctx.fillText(truncateForShare(submittedA), textAreaX + 16, 246);
  ctx.fillText(truncateForShare(submittedB), textAreaX + 16, 368);

  const bars = (result.dimensions || []).slice(0, 5);
  const barsTop = 432;
  const zeroX = textAreaX + 300;
  const maxHalf = 250;
  const maxAbs = Math.max(0.0001, ...bars.map((row) => Math.abs(Number(row.delta || 0))));
  ctx.font = '15px "IBM Plex Mono", monospace';
  bars.forEach((row, idx) => {
    const y = barsTop + idx * 36;
    const delta = Number(row.delta || 0);
    const mag = Math.abs(delta) / maxAbs;
    const width = Math.max(2, Math.round(mag * maxHalf));
    ctx.fillStyle = "#cbd5e1";
    ctx.fillText(row.label, textAreaX, y);
    ctx.fillStyle = "#374151";
    ctx.fillRect(zeroX - maxHalf, y + 8, maxHalf * 2, 10);
    ctx.fillStyle = delta >= 0 ? "#2dd4bf" : "#fb7185";
    if (delta >= 0) {
      ctx.fillRect(zeroX, y + 8, width, 10);
    } else {
      ctx.fillRect(zeroX - width, y + 8, width, 10);
    }
    ctx.fillStyle = "#e5e7eb";
    ctx.fillText(`${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`, textAreaX + 570, y);
  });
  ctx.fillStyle = "#4b5563";
  ctx.fillRect(zeroX - 1, barsTop + 6, 2, 36 * 5 - 18);

  const heatmap = await loadImage(heatmapImg.src);
  const heatmapW = 430;
  const heatmapH = 300;
  const heatmapX = canvas.width - 48 - heatmapW;
  const heatmapY = 214;
  ctx.fillStyle = "#151924";
  ctx.fillRect(heatmapX - 8, heatmapY - 8, heatmapW + 16, heatmapH + 16);
  ctx.drawImage(heatmap, heatmapX, heatmapY, heatmapW, heatmapH);

  const dateTag = new Date().toISOString().slice(0, 10);
  const revision = String(result.meta.model_revision || "unknown").slice(0, 36);
  const atlas = String(result.meta.atlas || "unknown");
  ctx.fillStyle = "#9ca3af";
  ctx.font = '14px "IBM Plex Mono", monospace';
  ctx.textAlign = "left";
  ctx.fillText(`model:${revision} atlas:${atlas} date:${dateTag}`, 48, 646);
  ctx.textAlign = "right";
  ctx.fillText("braindiff.xyz", 1152, 646);

  return await new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("Unable to encode share image"));
        return;
      }
      resolve(blob);
    }, "image/png");
  });
}

async function pollStatus(jobId) {
  while (true) {
    const res = await fetch(`/api/diff/status/${jobId}`);
    if (!res.ok) {
      throw new Error(`Status request failed (${res.status})`);
    }
    const payload = await res.json();
    const events = payload.events || [];
    events.forEach((event) => {
      if (event.status === "slow_processing") {
        loadingHintEl.textContent = "Still processing - longer texts take more time";
      } else {
        markLoadingStep(event.status);
      }
    });
    if (payload.status === "done") {
      return payload.result;
    }
    if (payload.status === "error") {
      throw new Error(formatJobError(payload.error));
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

async function runDiff() {
  if (isSubmitting) return;
  if (!textA.value.trim() || !textB.value.trim()) {
    if (!textA.value.trim()) textA.classList.add("shake");
    if (!textB.value.trim()) textB.classList.add("shake");
    setTimeout(() => {
      textA.classList.remove("shake");
      textB.classList.remove("shake");
    }, 280);
    return;
  }
  landingEl.classList.add("hidden");
  loadingEl.classList.remove("hidden");
  resultEl.classList.add("hidden");
  resetLoadingSteps();
  isSubmitting = true;
  runBtn.disabled = true;
  retryBtn.disabled = true;
  const submittedA = textA.value;
  const submittedB = textB.value;
  try {
    const startRes = await fetch("/api/diff/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text_a: submittedA, text_b: submittedB }),
    });
    if (!startRes.ok) {
      throw new Error(`Start request failed (${startRes.status})`);
    }
    const start = await startRes.json();
    const result = await pollStatus(start.job_id);
    loadingEl.classList.add("hidden");
    landingEl.classList.remove("hidden");
    choreographReveal(result);
    resultJson.textContent = JSON.stringify(result, null, 2);
    latestShareData = {
      result,
      textA: submittedA,
      textB: submittedB,
    };
  } catch (err) {
    loadingHintEl.textContent = `Something went wrong: ${err.message}`;
    retryBtn.classList.remove("hidden");
    retryBtn.disabled = false;
  } finally {
    isSubmitting = false;
    updateFormState();
  }
}

textA.addEventListener("input", updateFormState);
textB.addEventListener("input", updateFormState);
runBtn.addEventListener("click", runDiff);
retryBtn.addEventListener("click", runDiff);
shareBtn.addEventListener("click", () => {
  shareBtn.classList.add("shake");
  setTimeout(() => shareBtn.classList.remove("shake"), 260);
  buildShareImageBlob()
    .then(async (blob) => {
      try {
        await navigator.clipboard.write([
          new ClipboardItem({
            [blob.type]: blob,
          }),
        ]);
        shareBtn.textContent = "Copied share image!";
      } catch {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "brain-diff-share.png";
        a.click();
        URL.revokeObjectURL(url);
        shareBtn.textContent = "Downloaded share image";
      }
      setTimeout(() => {
        shareBtn.textContent = "Share";
      }, 1800);
    })
    .catch((err) => {
      shareBtn.textContent = err.message || "Share failed";
      setTimeout(() => {
        shareBtn.textContent = "Share";
      }, 1800);
    });
});
exampleBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    textA.value = btn.dataset.a || "";
    textB.value = btn.dataset.b || "";
    updateFormState();
  });
});
updateFormState();

