/**
 * TradingView-style Comparison Chart for one cortical dimension.
 *
 * Two smooth curves (A in slate-blue, B in vermillion) overlaid against a
 * shared time axis with a 0–1 activation y-axis. Mode toggle:
 *   - Absolute: both curves on the [0, 1] axis
 *   - Δ B−A:    a single difference curve with vermillion fill above zero
 *               (B winning) and slate-blue fill below zero (A winning)
 *
 * Crosshair follows the mouse; tooltip shows the exact A, B, and Δ at the
 * time under the cursor. Strip of 7 sparkline thumbnails at the bottom —
 * click to swap which dimension fills the main chart. Smooth crossfade
 * (200ms) when switching dimensions or modes.
 *
 * Vanilla SVG. No financial-charting library — just primitive paths.
 * Cream theme; respects --accent (B) and --good (A).
 */

const DIM_ORDER = [
  "attention_salience",
  "memory_encoding",
  "personal_resonance",
  "gut_reaction",
  "social_thinking",
  "language_depth",
  "brain_effort",
];

function $(s, r = document) { return r.querySelector(s); }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
function fmtTime(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function dimRowFor(rows, key) {
  return rows.find((r) => r.key === key) || null;
}

/** Build an SVG smooth-curve path from y values across an x axis. */
function pathFromValues(values, width, height, padding) {
  if (!values.length) return "";
  const n = values.length;
  const stepX = (width - padding * 2) / Math.max(1, n - 1);
  const points = values.map((v, i) => {
    const x = padding + i * stepX;
    const y = padding + (1 - Math.max(0, Math.min(1, v))) * (height - padding * 2);
    return [x, y];
  });
  // Catmull-Rom-ish smoothing for visual softness.
  let d = `M ${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
  for (let i = 1; i < points.length; i += 1) {
    const [x1, y1] = points[i - 1];
    const [x2, y2] = points[i];
    const cx = (x1 + x2) / 2;
    d += ` Q ${cx.toFixed(1)} ${y1.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }
  return d;
}

function pathDeltaFromValues(deltaValues, width, height, padding) {
  // Delta values can range [-1, 1]; centre y = the middle of the chart.
  if (!deltaValues.length) return "";
  const n = deltaValues.length;
  const stepX = (width - padding * 2) / Math.max(1, n - 1);
  const midY = padding + (height - padding * 2) / 2;
  const halfH = (height - padding * 2) / 2;
  const points = deltaValues.map((v, i) => {
    const x = padding + i * stepX;
    const y = midY - Math.max(-1, Math.min(1, v)) * halfH;
    return [x, y];
  });
  let d = `M ${points[0][0].toFixed(1)} ${points[0][1].toFixed(1)}`;
  for (let i = 1; i < points.length; i += 1) {
    const [x1, y1] = points[i - 1];
    const [x2, y2] = points[i];
    const cx = (x1 + x2) / 2;
    d += ` Q ${cx.toFixed(1)} ${y1.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }
  return d;
}

/** Append a closing segment so we can fill the area under a curve. */
function pathAreaFromCurve(curveD, width, height, padding) {
  if (!curveD) return "";
  return `${curveD} L ${width - padding} ${height - padding} L ${padding} ${height - padding} Z`;
}

function pathDeltaArea(deltaValues, width, height, padding, sign) {
  // sign = +1 for above-zero (B winning, vermillion fill),
  //       -1 for below-zero (A winning, slate-blue fill).
  if (!deltaValues.length) return "";
  const n = deltaValues.length;
  const stepX = (width - padding * 2) / Math.max(1, n - 1);
  const midY = padding + (height - padding * 2) / 2;
  const halfH = (height - padding * 2) / 2;
  const baseline = midY;
  let d = `M ${padding} ${baseline.toFixed(1)}`;
  for (let i = 0; i < deltaValues.length; i += 1) {
    const x = padding + i * stepX;
    let v = deltaValues[i];
    // Clamp so the area is only on the correct side of zero.
    if (sign > 0) v = Math.max(0, v);
    else v = Math.min(0, v);
    const y = midY - Math.max(-1, Math.min(1, v)) * halfH;
    d += ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
  }
  d += ` L ${(width - padding).toFixed(1)} ${baseline.toFixed(1)} Z`;
  return d;
}

function gridLines(width, height, padding, mode) {
  // Horizontal gridlines at y = 0.0, 0.5, 1.0 (absolute) or +0.5, 0, -0.5 (delta)
  const lines = [];
  const innerH = height - padding * 2;
  const labels = mode === "delta"
    ? [["+0.5", padding], ["0", padding + innerH / 2], ["-0.5", padding + innerH]]
    : [["1.0", padding], ["0.5", padding + innerH / 2], ["0.0", padding + innerH]];
  for (const [text, y] of labels) {
    lines.push(`<line x1="${padding}" y1="${y}" x2="${width - padding}" y2="${y}" stroke="currentColor" stroke-width="0.5" stroke-dasharray="3 3" opacity="0.18" />`);
    lines.push(`<text x="${padding - 6}" y="${y}" text-anchor="end" dominant-baseline="middle" class="cmp-axis-label">${text}</text>`);
  }
  return lines.join("");
}

function findPeak(values) {
  let bestIdx = 0;
  let bestVal = -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    if (values[i] > bestVal) { bestVal = values[i]; bestIdx = i; }
  }
  return { index: bestIdx, value: bestVal };
}

function mean(values) {
  if (!values.length) return 0;
  let total = 0;
  for (const v of values) total += v;
  return total / values.length;
}

function buildSparkline(values, isActive) {
  if (!values.length) return "";
  const W = 90, H = 28;
  const stepX = W / Math.max(1, values.length - 1);
  const points = values
    .map((v, i) => `${(i * stepX).toFixed(1)},${(H - Math.max(0, Math.min(1, v)) * H).toFixed(1)}`)
    .join(" ");
  return `<svg class="cmp-spark ${isActive ? 'is-active' : ''}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" preserveAspectRatio="none"><polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.5" /></svg>`;
}

/**
 * Public mount. Renders the comparison chart into `root`.
 *
 * @param {HTMLElement} root
 * @param {{dimensions: Array, durationA: number, durationB: number}} data
 */
export function renderComparisonChart(root, data) {
  if (!root) return;
  const dims = (data.dimensions || []).slice();
  if (!dims.length) {
    root.innerHTML = `<div class="cmp-empty">No dimensional timeseries available for this run.</div>`;
    return;
  }
  // Order dims canonically when present; surface unknowns at the end.
  dims.sort((a, b) => {
    const ai = DIM_ORDER.indexOf(a.key);
    const bi = DIM_ORDER.indexOf(b.key);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });

  const state = {
    dimIndex: 0,
    mode: "absolute",
    crosshair: null,
  };

  function activeDim() { return dims[state.dimIndex]; }
  const totalDuration = Math.max(data.durationA || 0, data.durationB || 0, 1);

  function paint() {
    const dim = activeDim();
    const a = (dim.timeseries_a || []).slice();
    const b = (dim.timeseries_b || []).slice();
    const n = Math.max(a.length, b.length);
    if (n === 0) {
      root.innerHTML = `<div class="cmp-empty">No timeseries data for ${escapeHtml(dim.label || dim.key)}.</div>`;
      return;
    }
    // Pad shorter side with last value so curves render cleanly even if A/B have different lengths.
    const padTo = (xs) => {
      while (xs.length < n) xs.push(xs[xs.length - 1] ?? 0);
      return xs;
    };
    const aPad = padTo(a);
    const bPad = padTo(b);
    const delta = aPad.map((v, i) => bPad[i] - v);

    const meanA = mean(aPad);
    const meanB = mean(bPad);
    const peakB = findPeak(bPad);
    const peakA = findPeak(aPad);
    const dimLabel = dim.label || dim.key;
    const region = dim.region || "";
    const meanDelta = (meanB - meanA);
    const deltaSign = meanDelta >= 0 ? "+" : "";

    const W = root.clientWidth || 760;
    const H = 360;
    const padding = 28;
    const aPath = pathFromValues(aPad, W, H, padding);
    const bPath = pathFromValues(bPad, W, H, padding);
    const aArea = pathAreaFromCurve(aPath, W, H, padding);
    const bArea = pathAreaFromCurve(bPath, W, H, padding);
    const deltaPath = pathDeltaFromValues(delta, W, H, padding);
    const deltaPosArea = pathDeltaArea(delta, W, H, padding, +1);
    const deltaNegArea = pathDeltaArea(delta, W, H, padding, -1);

    // Peak markers in absolute mode.
    const peakStepX = (W - padding * 2) / Math.max(1, n - 1);
    const peakAX = padding + peakA.index * peakStepX;
    const peakAY = padding + (1 - peakA.value) * (H - padding * 2);
    const peakBX = padding + peakB.index * peakStepX;
    const peakBY = padding + (1 - peakB.value) * (H - padding * 2);

    const isAbsolute = state.mode === "absolute";

    root.innerHTML = `
      <div class="cmp-toolbar">
        <div class="cmp-toolbar-left">
          <div class="cmp-asset">
            <span class="cmp-name">${escapeHtml(dimLabel)}</span>
            <span class="cmp-region">${escapeHtml(region)}</span>
          </div>
          <div class="cmp-stats">
            <span><span class="muted">A</span> <strong>${meanA.toFixed(2)}</strong></span>
            <span><span class="muted">B</span> <strong>${meanB.toFixed(2)}</strong></span>
            <span><span class="muted">Δ</span> <strong class="${meanDelta >= 0 ? 'pos' : 'neg'}">${deltaSign}${meanDelta.toFixed(2)}</strong></span>
            <span><span class="muted">PEAK B @</span> <strong>${fmtTime(peakB.index * (totalDuration / Math.max(1, n - 1)))}</strong></span>
          </div>
        </div>
        <div class="cmp-toolbar-right" role="tablist" aria-label="Chart mode">
          <button class="cmp-mode-btn ${isAbsolute ? 'is-active' : ''}" data-mode="absolute" type="button">Absolute</button>
          <button class="cmp-mode-btn ${!isAbsolute ? 'is-active' : ''}" data-mode="delta" type="button">Δ B − A</button>
        </div>
      </div>
      <div class="cmp-chart-wrap">
        <svg class="cmp-chart-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
          <g class="cmp-grid">${gridLines(W, H, padding, state.mode)}</g>
          ${isAbsolute ? `
            <path class="cmp-area-a" d="${aArea}" fill="var(--good, #2a5583)" opacity="0.10" />
            <path class="cmp-area-b" d="${bArea}" fill="var(--accent, #c1272d)" opacity="0.10" />
            <path class="cmp-line-a" d="${aPath}" fill="none" stroke="var(--good, #2a5583)" stroke-width="2.2" />
            <path class="cmp-line-b" d="${bPath}" fill="none" stroke="var(--accent, #c1272d)" stroke-width="2.2" />
            <circle class="cmp-peak a" cx="${peakAX}" cy="${peakAY}" r="5" fill="none" stroke="var(--good, #2a5583)" stroke-width="2" />
            <circle class="cmp-peak b" cx="${peakBX}" cy="${peakBY}" r="5" fill="none" stroke="var(--accent, #c1272d)" stroke-width="2" />
          ` : `
            <path class="cmp-area-pos" d="${deltaPosArea}" fill="var(--accent, #c1272d)" opacity="0.18" />
            <path class="cmp-area-neg" d="${deltaNegArea}" fill="var(--good, #2a5583)" opacity="0.18" />
            <path class="cmp-line-delta" d="${deltaPath}" fill="none" stroke="currentColor" stroke-width="2" />
          `}
          <line class="cmp-crosshair-v" x1="0" y1="0" x2="0" y2="${H}" stroke="currentColor" stroke-width="0.8" opacity="0" />
        </svg>
        <div class="cmp-tooltip" hidden>
          <div class="cmp-tt-time">0:00</div>
          <div class="cmp-tt-row a"><span>A</span><strong class="cmp-tt-a">—</strong></div>
          <div class="cmp-tt-row b"><span>B</span><strong class="cmp-tt-b">—</strong></div>
          <div class="cmp-tt-row d"><span>Δ</span><strong class="cmp-tt-d">—</strong></div>
        </div>
      </div>
      <div class="cmp-thumbs" role="tablist" aria-label="Cortical dimension">
        ${dims.map((d, i) => `
          <button class="cmp-thumb ${i === state.dimIndex ? 'is-active' : ''}" data-dim-index="${i}" type="button">
            <span class="cmp-thumb-name">${escapeHtml(d.label || d.key)}</span>
            ${buildSparkline((d.timeseries_b || []).slice(0, 60), i === state.dimIndex)}
          </button>
        `).join("")}
      </div>
    `;

    // Wire toolbar mode buttons.
    root.querySelectorAll(".cmp-mode-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.dataset.mode;
        if (mode === state.mode) return;
        state.mode = mode;
        paint();
      });
    });

    // Wire dimension thumbnails.
    root.querySelectorAll(".cmp-thumb").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.dataset.dimIndex);
        if (idx === state.dimIndex) return;
        state.dimIndex = idx;
        paint();
      });
    });

    // Crosshair + tooltip on mousemove.
    const svg = root.querySelector(".cmp-chart-svg");
    const crossLine = svg.querySelector(".cmp-crosshair-v");
    const tooltip = root.querySelector(".cmp-tooltip");
    const ttA = tooltip.querySelector(".cmp-tt-a");
    const ttB = tooltip.querySelector(".cmp-tt-b");
    const ttD = tooltip.querySelector(".cmp-tt-d");
    const ttTime = tooltip.querySelector(".cmp-tt-time");

    function updateCrosshair(clientX) {
      const rect = svg.getBoundingClientRect();
      const localX = ((clientX - rect.left) / rect.width) * W;
      if (localX < padding || localX > W - padding) {
        crossLine.setAttribute("opacity", "0");
        tooltip.hidden = true;
        return;
      }
      const t = (localX - padding) / (W - padding * 2);
      const idx = Math.max(0, Math.min(n - 1, Math.round(t * (n - 1))));
      const aVal = aPad[idx] || 0;
      const bVal = bPad[idx] || 0;
      const dVal = bVal - aVal;
      const seconds = idx * (totalDuration / Math.max(1, n - 1));
      crossLine.setAttribute("x1", localX.toFixed(1));
      crossLine.setAttribute("x2", localX.toFixed(1));
      crossLine.setAttribute("opacity", "0.55");
      ttA.textContent = aVal.toFixed(2);
      ttB.textContent = bVal.toFixed(2);
      ttD.textContent = (dVal >= 0 ? "+" : "") + dVal.toFixed(2);
      ttD.className = "cmp-tt-d " + (dVal >= 0 ? "pos" : "neg");
      ttTime.textContent = fmtTime(seconds);
      tooltip.hidden = false;
      const wrapRect = root.querySelector(".cmp-chart-wrap").getBoundingClientRect();
      const tipX = clientX - wrapRect.left + 14;
      const tipY = (wrapRect.height / 2) - 60;
      tooltip.style.left = `${Math.min(tipX, wrapRect.width - 140)}px`;
      tooltip.style.top = `${Math.max(0, tipY)}px`;
    }
    root.querySelector(".cmp-chart-wrap").addEventListener("mousemove", (e) => updateCrosshair(e.clientX));
    root.querySelector(".cmp-chart-wrap").addEventListener("mouseleave", () => {
      crossLine.setAttribute("opacity", "0");
      tooltip.hidden = true;
    });
  }

  paint();
  // Repaint on window resize so SVG width tracks responsively.
  let resizeTimer = 0;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(paint, 120);
  });
}
