/**
 * Structural Skeleton — 4-lane timeline of when content changes.
 *
 * Lanes top-to-bottom: TEXT (gold) / VISUAL (cool blue) / AUDIO (coral)
 * / ALIGNMENT (vermillion bars where ≥2 lanes coincide).
 *
 * Each event marker is a vertical line with a dot at the top, like a
 * measure line in a music score. Hover for the event's specifics
 * (text segments, magnitude, RMS values). The summary line below
 * counts events and the cross-modal alignment score.
 *
 * Vanilla SVG. Reads result.meta.media_features.skeleton.{a, b}.
 */

const LANE_COLORS = {
  text: "#C9A66B",     // gold (matches the mockup spec)
  visual: "#7FB3C6",   // cool blue
  audio: "#E25B43",    // coral
};

function $(s, r = document) { return r.querySelector(s); }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
function fmtTime(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function buildLane(label, events, totalDuration, color, formatter) {
  const W = 100; // percent units
  return `
    <div class="skeleton-lane" data-lane="${label.toLowerCase()}">
      <div class="skeleton-lane-label" style="color:${color}">${escapeHtml(label)}</div>
      <div class="skeleton-lane-track" style="--lane-color:${color}">
        ${events.map((ev) => {
          const pos = totalDuration > 0 ? (Number(ev.time || 0) / totalDuration) * W : 0;
          const tooltipBody = formatter(ev);
          return `
            <button class="skeleton-marker" style="left:${pos.toFixed(2)}%"
              type="button"
              data-time="${Number(ev.time || 0)}"
              data-tooltip="${escapeHtml(tooltipBody)}"
              aria-label="${escapeHtml(label)} event at ${fmtTime(ev.time)}">
              <span class="skeleton-marker-dot"></span>
              <span class="skeleton-marker-stem"></span>
            </button>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function buildAlignmentLane(alignment, totalDuration) {
  const moments = (alignment && alignment.aligned_moments) || [];
  if (!moments.length) {
    return `
      <div class="skeleton-lane skeleton-lane-alignment">
        <div class="skeleton-lane-label">ALIGNMENT</div>
        <div class="skeleton-lane-track skeleton-empty-track">
          <span class="skeleton-empty-text">No cross-modal coincidence detected.</span>
        </div>
      </div>
    `;
  }
  return `
    <div class="skeleton-lane skeleton-lane-alignment">
      <div class="skeleton-lane-label">ALIGNMENT</div>
      <div class="skeleton-lane-track">
        ${moments.map((m) => {
          const pos = totalDuration > 0 ? (Number(m.time || 0) / totalDuration) * 100 : 0;
          const modalities = (m.modalities || []).join(" + ");
          return `
            <button class="skeleton-alignment-bar"
              style="left:${pos.toFixed(2)}%"
              type="button"
              data-time="${Number(m.time || 0)}"
              data-tooltip="${escapeHtml(`Aligned at ${fmtTime(m.time)}: ${modalities}`)}"
              aria-label="Aligned moment at ${fmtTime(m.time)}: ${modalities}">
            </button>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function buildTimeRuler(totalDuration) {
  const tickCount = Math.max(2, Math.min(6, Math.round(totalDuration / 5)));
  const ticks = [];
  for (let i = 0; i <= tickCount; i += 1) {
    const t = (totalDuration * i) / tickCount;
    ticks.push({ pct: (i / tickCount) * 100, t });
  }
  return `
    <div class="skeleton-ruler">
      ${ticks.map((tk) => `<span class="skeleton-tick" style="left:${tk.pct}%">${fmtTime(tk.t)}</span>`).join("")}
    </div>
  `;
}

function formatTextEvent(ev) {
  const before = ev.before_summary ? `Before: "${ev.before_summary}"` : "";
  const after = ev.after_summary ? `After: "${ev.after_summary}"` : "";
  const distance = ev.distance != null ? `· cosine distance ${Number(ev.distance).toFixed(2)}` : "";
  return [`Topic shift @ ${fmtTime(ev.time)} ${distance}`, before, after].filter(Boolean).join(" — ");
}
function formatVisualEvent(ev) {
  const mag = ev.magnitude != null ? ` · cadence ${Number(ev.magnitude).toFixed(2)}/s` : "";
  return `${ev.type === "scene_open" ? "Scene open" : "Scene cut"} @ ${fmtTime(ev.time)}${mag}`;
}
function formatAudioEvent(ev) {
  if (ev.type === "energy_spike") {
    return `Energy spike @ ${fmtTime(ev.time)} · RMS ${Number(ev.rms || 0).toFixed(2)} (z=${Number(ev.z || 0).toFixed(1)})`;
  }
  if (ev.type === "silence_start") {
    return `Silence starts @ ${fmtTime(ev.time)} · ${Number(ev.duration_seconds || 0).toFixed(1)}s long`;
  }
  return `${ev.type} @ ${fmtTime(ev.time)}`;
}

function buildSideBlock(side, label, sideKey, totalDuration) {
  if (!side) {
    return `<div class="skeleton-side skeleton-empty"><div class="skeleton-side-head"><span class="badge ${sideKey}">${sideKey.toUpperCase()}</span> ${escapeHtml(label)}</div><p>No skeleton data available.</p></div>`;
  }
  const text = side.text_events || [];
  const visual = side.visual_events || [];
  const audio = side.audio_events || [];
  return `
    <div class="skeleton-side">
      <div class="skeleton-side-head">
        <span class="badge ${sideKey}">${sideKey.toUpperCase()}</span>
        <span class="skeleton-side-name">${escapeHtml(label)}</span>
      </div>
      ${buildTimeRuler(totalDuration)}
      ${buildLane("TEXT", text, totalDuration, LANE_COLORS.text, formatTextEvent)}
      ${buildLane("VISUAL", visual, totalDuration, LANE_COLORS.visual, formatVisualEvent)}
      ${buildLane("AUDIO", audio, totalDuration, LANE_COLORS.audio, formatAudioEvent)}
      ${buildAlignmentLane(side.alignment, totalDuration)}
      <p class="skeleton-summary">${escapeHtml(side.summary_line || "")}</p>
    </div>
  `;
}

/**
 * Mount the structural-skeleton view into `root`.
 *
 * @param {HTMLElement} root
 * @param {Object} skeleton  - meta.media_features.skeleton: {a, b, structural_similarity}
 * @param {Object} opts      - {durationA, durationB, labelA, labelB}
 */
export function renderSkeleton(root, skeleton, opts = {}) {
  if (!root) return;
  if (!skeleton || (!skeleton.a && !skeleton.b)) {
    root.innerHTML = `<div class="skeleton-empty-card">Structural skeleton not available for this run.</div>`;
    return;
  }
  const durationA = opts.durationA || 30;
  const durationB = opts.durationB || 30;
  const labelA = opts.labelA || "Version A";
  const labelB = opts.labelB || "Version B";
  const structSim = typeof skeleton.structural_similarity === "number"
    ? skeleton.structural_similarity
    : null;

  root.innerHTML = `
    <div class="skeleton-head">
      <p class="micro">Structural Skeleton</p>
      <h2>When the content changes</h2>
      <p class="skeleton-sub">
        Three lanes: TEXT (topic shifts in the transcript), VISUAL (scene cuts
        from keyframes), AUDIO (energy spikes and silences in the waveform).
        The fourth lane shows where two or more lanes coincide within one
        second — your content's <em>rhythm</em>.
        <a href="/methodology/skeleton">How we detect this →</a>
      </p>
      ${structSim !== null ? `<p class="skeleton-structsim">
        Structural similarity between A and B: <strong>${structSim.toFixed(2)}</strong>
        <span class="muted">(1.00 = identical event-type composition; 0.00 = nothing in common)</span>
      </p>` : ""}
    </div>
    <div class="skeleton-stack">
      ${buildSideBlock(skeleton.a, labelA, "a", durationA)}
      ${buildSideBlock(skeleton.b, labelB, "b", durationB)}
    </div>
    <div class="skeleton-tooltip" hidden></div>
  `;

  wireTooltips(root);
}

function wireTooltips(root) {
  const tt = root.querySelector(".skeleton-tooltip");
  if (!tt) return;
  // Tooltip on event marker hover.
  function showTip(e) {
    const target = e.currentTarget;
    const text = target.getAttribute("data-tooltip") || "";
    if (!text) return;
    tt.textContent = text;
    tt.hidden = false;
    const rect = root.getBoundingClientRect();
    tt.style.left = `${e.clientX - rect.left + 12}px`;
    tt.style.top = `${e.clientY - rect.top + 12}px`;
  }
  function hideTip() { tt.hidden = true; }
  root.querySelectorAll(".skeleton-marker, .skeleton-alignment-bar").forEach((node) => {
    node.addEventListener("mousemove", showTip);
    node.addEventListener("mouseleave", hideTip);
  });
}
