/**
 * Spectrogram — 7 cortical systems × time grid, color-encoded by activation.
 *
 * Renders two stacked spectrograms (Version A on top, Version B on bottom)
 * as a single SVG. Each cell is colored by its activation value, with the
 * pattern strip below each video showing detected co-activation patterns
 * as inscribed colored blocks at their time positions.
 *
 * Vanilla SVG, no D3. Cream theme uses --good (slate-blue, low) → --bg-3
 * (mid) → --accent (vermillion, high) gradient. Hover any cell for the
 * exact value + dim label + timestamp.
 */

import { renderPatternStrip } from "./patterns.js";

const DIM_ORDER = [
  "personal_resonance",
  "attention_salience",
  "brain_effort",
  "gut_reaction",
  "memory_encoding",
  "social_thinking",
  "language_depth",
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

/**
 * Color a cell based on its activation value (0..1).
 * Theme-aware. Light: slate (low) → cream-mid → vermillion (high).
 *               Dark: cool blue (low) → dark mid → coral (high).
 * The mid stop matters — in dark theme, a cream mid blends into nothing,
 * so we pick a low-luminance neutral that reads on the bg without flatlining.
 * Returns an rgb() string.
 */
function isDarkTheme() {
  try {
    return document.documentElement.getAttribute("data-theme") === "dark";
  } catch (_) { return true; }
}
function paletteStops() {
  if (isDarkTheme()) {
    return [
      { stop: 0.0, rgb: [127, 179, 198] }, // --a (cool blue)
      { stop: 0.5, rgb: [40, 40, 60] },    // dark mid neutral, reads on bg #08080F
      { stop: 1.0, rgb: [226, 91, 67] },   // --accent (coral)
    ];
  }
  return [
    { stop: 0.0, rgb: [42, 85, 131] },     // --good slate
    { stop: 0.5, rgb: [200, 192, 174] },   // cream mid — reads on cream bg
    { stop: 1.0, rgb: [193, 39, 45] },     // --accent vermillion
  ];
}
function colorForValue(v) {
  const value = Math.max(0, Math.min(1, v));
  const stops = paletteStops();
  let lo = stops[0], hi = stops[1];
  for (let i = 1; i < stops.length; i += 1) {
    if (value <= stops[i].stop) { hi = stops[i]; lo = stops[i - 1]; break; }
  }
  const t = (value - lo.stop) / Math.max(1e-6, hi.stop - lo.stop);
  const r = Math.round(lo.rgb[0] + (hi.rgb[0] - lo.rgb[0]) * t);
  const g = Math.round(lo.rgb[1] + (hi.rgb[1] - lo.rgb[1]) * t);
  const b = Math.round(lo.rgb[2] + (hi.rgb[2] - lo.rgb[2]) * t);
  return `rgb(${r},${g},${b})`;
}

/**
 * Build the SVG for one side (A or B).
 *
 * @param {Array} dimensionRows  - the result.dimensions[] list from the worker
 * @param {string} side           - "a" or "b"
 * @param {Object} layout         - {width, rowHeight, gap}
 */
function buildSpectrogramSVG(dimensionRows, side, layout) {
  const field = side === "a" ? "timeseries_a" : "timeseries_b";
  // Use the dim order as our row order; gracefully skip dims not present.
  const rows = DIM_ORDER.map((k) => dimRowFor(dimensionRows, k)).filter(Boolean);
  if (!rows.length) return { svg: "", n_steps: 0 };
  const n_steps = Math.max(...rows.map((r) => (r[field] || []).length));
  if (n_steps === 0) return { svg: "", n_steps: 0 };

  const cellW = layout.width / n_steps;
  const cellH = layout.rowHeight;
  const totalH = rows.length * cellH;

  const cellsSvg = rows
    .map((row, ri) => {
      const series = row[field] || [];
      const cells = series
        .map((v, ti) => {
          const x = ti * cellW;
          const y = ri * cellH;
          const fill = colorForValue(v);
          const label = `${row.label || row.key} · ${fmtTime(ti)} · ${Number(v).toFixed(2)}`;
          return `<rect class="spectro-cell" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${cellW.toFixed(2)}" height="${cellH.toFixed(2)}" fill="${fill}" data-label="${escapeHtml(label)}" />`;
        })
        .join("");
      return cells;
    })
    .join("");

  const labelsSvg = rows
    .map((row, ri) => {
      const y = ri * cellH + cellH / 2;
      return `
        <g class="spectro-row-label">
          <text x="${-8}" y="${y.toFixed(2)}" text-anchor="end" dominant-baseline="middle">${escapeHtml(row.label || row.key)}</text>
          <text class="spectro-row-region" x="${-8}" y="${(y + 13).toFixed(2)}" text-anchor="end" dominant-baseline="middle">${escapeHtml(row.region || "")}</text>
        </g>
      `;
    })
    .join("");

  return {
    svg: `
      <svg class="spectro-svg" viewBox="-160 -8 ${layout.width + 168} ${totalH + 24}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Cortical activation spectrogram">
        <g class="spectro-cells">${cellsSvg}</g>
        <g class="spectro-labels">${labelsSvg}</g>
      </svg>
    `,
    n_steps,
    height: totalH,
    rows: rows.length,
  };
}

function buildXAxis(n_steps, durationSeconds, width) {
  // 6 evenly spaced ticks. If duration < 6s, one per second.
  const tickCount = Math.min(6, Math.max(2, Math.round(durationSeconds / 5)));
  const ticks = [];
  for (let i = 0; i <= tickCount; i += 1) {
    const t = (durationSeconds * i) / tickCount;
    const x = (width * i) / tickCount;
    ticks.push({ x, t });
  }
  return `
    <div class="spectro-axis-x">
      ${ticks.map((tk) => `<span class="spectro-tick" style="left:${tk.x}px">${fmtTime(tk.t)}</span>`).join("")}
    </div>
  `;
}

function buildScaleLegend() {
  return `
    <div class="spectro-scale" aria-label="Activation scale">
      <div class="spectro-scale-bar"></div>
      <div class="spectro-scale-labels">
        <span>0.0</span><span>0.5</span><span>1.0</span>
      </div>
      <div class="spectro-scale-caption">Predicted activation (population-average cortex)</div>
    </div>
  `;
}

/**
 * Render a side's spectrogram + pattern strip into `root`.
 *
 * @param {HTMLElement} root
 * @param {{dimensions: Array, patterns: Array, duration: number, label: string, side: 'a'|'b'}} data
 */
async function renderOneSide(root, data) {
  const layout = { width: root.clientWidth || 720, rowHeight: 26 };
  // Reserve space for the labels (we draw them in negative-x territory of
  // the SVG). Available width for cells = layout.width - 0 (the SVG handles
  // the 160px label margin via viewBox and overflow:visible).
  const built = buildSpectrogramSVG(data.dimensions, data.side, layout);
  if (!built.svg) {
    root.innerHTML = `<div class="spectro-empty">No dimensional timeseries available for this side.</div>`;
    return;
  }
  root.innerHTML = `
    <div class="spectro-side-head"><span class="badge ${data.side}">${data.side.toUpperCase()}</span> ${escapeHtml(data.label || (data.side === "a" ? "Version A" : "Version B"))}</div>
    <div class="spectro-canvas-wrap">${built.svg}</div>
    ${buildXAxis(built.n_steps, data.duration || built.n_steps, layout.width)}
    <div class="spectro-pattern-strip" data-pattern-side="${data.side}"></div>
  `;
  // Mount the existing pattern strip component below the spectrogram so
  // co-activation blocks line up time-wise with the cells above.
  const stripRoot = root.querySelector(".spectro-pattern-strip");
  await renderPatternStrip(stripRoot, data.patterns || [], data.duration || built.n_steps);
  // Hover tooltip
  const tooltip = ensureTooltip(root.parentNode);
  root.querySelectorAll(".spectro-cell").forEach((cell) => {
    cell.addEventListener("mousemove", (e) => {
      const text = cell.getAttribute("data-label");
      tooltip.textContent = text;
      tooltip.hidden = false;
      const containerRect = root.parentNode.getBoundingClientRect();
      tooltip.style.left = `${e.clientX - containerRect.left + 12}px`;
      tooltip.style.top = `${e.clientY - containerRect.top + 12}px`;
    });
    cell.addEventListener("mouseleave", () => { tooltip.hidden = true; });
  });
}

function ensureTooltip(container) {
  let tt = container.querySelector(".spectro-tooltip");
  if (!tt) {
    tt = document.createElement("div");
    tt.className = "spectro-tooltip";
    tt.hidden = true;
    container.appendChild(tt);
  }
  return tt;
}

/**
 * Public entry point. Mounts the full spectrogram (A + B + scale legend)
 * into `root` from a result payload.
 */
export async function renderSpectrogram(root, { dimensions, patterns, durationA, durationB, labelA, labelB }) {
  if (!root) return;
  if (!dimensions || !dimensions.length) {
    root.innerHTML = `<div class="spectro-empty">No dimensional timeseries available for this run.</div>`;
    return;
  }
  root.innerHTML = `
    <div class="spectro-head">
      <p class="micro">Spectrogram</p>
      <h2>Seven cortical systems, second by second</h2>
      <p class="spectro-sub">
        Each row is one cortical system. Each column is one second.
        Color encodes the population-average predicted activation.
        Co-activation patterns sit below each video as labeled blocks.
      </p>
    </div>
    <div class="spectro-stack">
      <div class="spectro-side" id="spectroSideA"></div>
      <div class="spectro-side" id="spectroSideB"></div>
    </div>
    ${buildScaleLegend()}
  `;
  await renderOneSide(root.querySelector("#spectroSideA"), {
    dimensions,
    patterns: patterns?.a || [],
    duration: durationA || 30,
    side: "a",
    label: labelA,
  });
  await renderOneSide(root.querySelector("#spectroSideB"), {
    dimensions,
    patterns: patterns?.b || [],
    duration: durationB || 30,
    side: "b",
    label: labelB,
  });
}
