/**
 * Co-activation pattern UI — used by both audio-results.js and
 * video-results.js. Renders:
 *
 *   1. Pattern Strip: a horizontal lane below the timeline where each
 *      detected pattern instance shows up as a colored block at its
 *      time position with the pattern name inscribed.
 *
 *   2. Pattern Card: opens when a strip block is clicked. Shows the
 *      pattern definition, the contributing-dimension mini-chart for
 *      this exact window, the threshold values used, the citation list,
 *      and a "How we detect this" expandable.
 *
 * Reads the canonical pattern definitions JSON (single source of truth
 * shared with the Python detector) so descriptions, thresholds, and
 * citations never drift between backend and frontend.
 */

const DEFINITIONS_URL = "/data/pattern-definitions.json";
let _cachedDefinitions = null;

async function loadDefinitions() {
  if (_cachedDefinitions) return _cachedDefinitions;
  try {
    const res = await fetch(DEFINITIONS_URL, { cache: "force-cache" });
    if (!res.ok) throw new Error(`pattern-definitions HTTP ${res.status}`);
    _cachedDefinitions = await res.json();
  } catch (err) {
    console.warn("patterns: failed to load definitions", err);
    _cachedDefinitions = { patterns: [] };
  }
  return _cachedDefinitions;
}

function definitionFor(definitions, patternId) {
  return (definitions.patterns || []).find((p) => p.id === patternId) || null;
}

/**
 * Render a Pattern Strip into `root` for one side's pattern instances.
 *
 * @param {HTMLElement} root - container element
 * @param {Array} instances - list of pattern instances (start_seconds, end_seconds, peak_seconds, pattern_id, ...)
 * @param {number} totalSeconds - the timeline span the strip is drawn over
 * @param {{onSelect: (instance, definition) => void}} opts
 */
export async function renderPatternStrip(root, instances, totalSeconds, opts = {}) {
  if (!root) return;
  const definitions = await loadDefinitions();
  if (!Array.isArray(instances) || instances.length === 0) {
    root.innerHTML = `<div class="pattern-strip-empty">
      No co-activation patterns detected for this side. Conservative thresholds may have suppressed weak signals — see the methodology page.
    </div>`;
    return;
  }
  const span = totalSeconds && totalSeconds > 0 ? totalSeconds : 1;
  const blocks = instances
    .map((inst) => {
      const def = definitionFor(definitions, inst.pattern_id);
      if (!def) return null;
      const startPct = Math.max(0, Math.min(100, (inst.start_seconds / span) * 100));
      const widthPct = Math.max(
        2,
        Math.min(100 - startPct, ((inst.end_seconds - inst.start_seconds) / span) * 100)
      );
      return { inst, def, startPct, widthPct };
    })
    .filter(Boolean);

  // We render blocks at fractional positions over a relatively-positioned
  // axis. Two patterns can co-occur (Learning Moment + Reasoning Beat at
  // the same second is genuinely possible) so we stack overlapping blocks
  // into rows: each new block goes into the first row whose existing
  // blocks don't intersect it.
  const rows = [];
  for (const b of blocks) {
    let placed = false;
    for (const row of rows) {
      const conflict = row.some(
        (existing) =>
          existing.startPct < b.startPct + b.widthPct &&
          existing.startPct + existing.widthPct > b.startPct
      );
      if (!conflict) {
        row.push(b);
        placed = true;
        break;
      }
    }
    if (!placed) rows.push([b]);
  }

  root.innerHTML = `
    <div class="pattern-strip-rail" role="list" aria-label="Detected co-activation patterns">
      ${rows
        .map(
          (row) => `
            <div class="pattern-strip-row">
              ${row
                .map(
                  ({ inst, def, startPct, widthPct }) => `
                    <button
                      class="pattern-block"
                      role="listitem"
                      type="button"
                      data-pattern-id="${escapeAttr(inst.pattern_id)}"
                      data-instance="${escapeAttr(JSON.stringify(inst))}"
                      style="left:${startPct.toFixed(2)}%;width:${widthPct.toFixed(2)}%;background:var(${def.color_token || "--accent"});"
                      title="${escapeAttr(def.name)} · ${formatTime(inst.start_seconds)}–${formatTime(inst.end_seconds)}"
                    >
                      <span class="pattern-block-name">${escapeHtml(def.name)}</span>
                      <span class="pattern-block-time">${formatTime(inst.start_seconds)}–${formatTime(inst.end_seconds)}</span>
                    </button>
                  `
                )
                .join("")}
            </div>
          `
        )
        .join("")}
    </div>
  `;

  root.querySelectorAll(".pattern-block").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pid = btn.getAttribute("data-pattern-id");
      const inst = JSON.parse(btn.getAttribute("data-instance"));
      const def = definitionFor(definitions, pid);
      if (def && opts.onSelect) opts.onSelect(inst, def);
      else if (def) openPatternCard(inst, def);
    });
  });
}

/**
 * Open the Pattern Card modal for one instance + its definition.
 * Called from the strip click handler unless the page intercepts via opts.onSelect.
 */
export function openPatternCard(instance, definition) {
  closeAnyOpenCard();
  const overlay = document.createElement("div");
  overlay.className = "pattern-card-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-labelledby", "patternCardTitle");
  overlay.setAttribute("aria-modal", "true");
  overlay.innerHTML = renderCardHTML(instance, definition);
  document.body.appendChild(overlay);
  // Focus the close button so keyboard users can dismiss immediately.
  const closer = overlay.querySelector("[data-close]");
  if (closer) closer.focus();
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay || e.target.closest("[data-close]")) closeAnyOpenCard();
  });
  document.addEventListener("keydown", escClose, { once: true });
}

function escClose(e) {
  if (e.key === "Escape") closeAnyOpenCard();
}

function closeAnyOpenCard() {
  document.querySelectorAll(".pattern-card-overlay").forEach((n) => n.remove());
}

function renderCardHTML(instance, def) {
  const dimValues = instance.contributing_dim_values || {};
  const thresholds = def.thresholds || {};
  const dims = def.dims || [];
  return `
    <div class="pattern-card-shell">
      <header class="pattern-card-head">
        <div>
          <div class="pattern-card-eyebrow">Detected pattern</div>
          <h2 class="pattern-card-title" id="patternCardTitle">${escapeHtml(def.name)}</h2>
          <p class="pattern-card-short">${escapeHtml(def.short_desc || "")}</p>
        </div>
        <button class="pattern-card-close" data-close type="button" aria-label="Close pattern detail">×</button>
      </header>
      <section class="pattern-card-body">
        <p class="pattern-card-long">${escapeHtml(def.long_desc || "")}</p>
        <div class="pattern-card-meta">
          <div>
            <span class="kicker">Window</span>
            <strong>${formatTime(instance.start_seconds)} – ${formatTime(instance.end_seconds)}</strong>
            <span class="muted">peak @ ${formatTime(instance.peak_seconds)}</span>
          </div>
          <div>
            <span class="kicker">Logic</span>
            <strong>${escapeHtml(def.logic || "AND_HIGH")}</strong>
            <span class="muted">min ${def.min_duration_seconds || 1}s</span>
          </div>
          <div>
            <span class="kicker">Peak intensity</span>
            <strong>${(instance.peak_intensity || 0).toFixed(3)}</strong>
            <span class="muted">mean of contributing dims</span>
          </div>
        </div>
        <div class="pattern-card-dims">
          ${dims
            .map((dimId) => {
              const values = dimValues[dimId] || [];
              const threshold = thresholds[dimId] ?? 0.5;
              return `
                <div class="pattern-dim">
                  <div class="pattern-dim-head">
                    <strong>${escapeHtml(prettyDim(dimId))}</strong>
                    <span class="muted">threshold ${threshold.toFixed(2)}</span>
                  </div>
                  ${miniChart(values, threshold)}
                </div>
              `;
            })
            .join("")}
        </div>
        <details class="pattern-card-howto">
          <summary>How we detect this</summary>
          <ol>
            <li>For each second in the run, check whether <strong>every</strong> contributing dimension is at or above its threshold.</li>
            <li>Group runs of consecutive in-pattern seconds into blocks.</li>
            <li>Drop blocks shorter than <strong>${def.min_duration_seconds || 1}s</strong> — sustained co-activation, not single-frame noise.</li>
            <li>Mark the within-block second with the highest mean activation as the peak.</li>
          </ol>
          <p class="muted">No machine learning. Same input → same output. The full algorithm is at <code>backend/pattern_detector.py</code>.</p>
        </details>
        <section class="pattern-card-cites">
          <h3>Citations</h3>
          <ul>
            ${(def.citations || [])
              .map(
                (c) => `
                  <li>
                    <span class="cite-authors">${escapeHtml(c.authors || "")}</span>
                    <span class="cite-year">(${c.year || ""})</span>,
                    <em>${escapeHtml(c.journal || "")}</em>.
                    <span class="cite-title">${escapeHtml(c.title || "")}</span>
                    ${
                      c.doi
                        ? `<a class="cite-link" href="https://doi.org/${encodeURIComponent(c.doi)}" target="_blank" rel="noopener">doi</a>`
                        : ""
                    }
                    ${
                      c.scholar_url
                        ? `<a class="cite-link" href="${encodeAttr(c.scholar_url)}" target="_blank" rel="noopener">scholar</a>`
                        : ""
                    }
                    ${c.claim ? `<div class="cite-claim">${escapeHtml(c.claim)}</div>` : ""}
                    ${
                      c.scope_caveat
                        ? `<div class="cite-caveat">⚠ ${escapeHtml(c.scope_caveat)}</div>`
                        : ""
                    }
                  </li>
                `
              )
              .join("")}
          </ul>
          <p class="cite-summary">${escapeHtml(def.citation_summary || "")}</p>
        </section>
        <div class="pattern-card-disclaimer">
          These are population-average predictions from TRIBE v2, computed on
          activation patterns aggregated across published fMRI studies. They
          are a vocabulary, not a diagnosis.
          <a href="/methodology/patterns">Read the methodology →</a>
        </div>
      </section>
    </div>
  `;
}

function miniChart(values, threshold) {
  if (!values.length) return `<div class="pattern-mini-empty">no data</div>`;
  const W = 220;
  const H = 36;
  const max = Math.max(...values, threshold, 0.6);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const stepX = W / Math.max(1, values.length - 1);
  const points = values
    .map((v, i) => `${(i * stepX).toFixed(2)},${(H - ((v - min) / span) * H).toFixed(2)}`)
    .join(" ");
  const thresholdY = H - ((threshold - min) / span) * H;
  return `
    <svg class="pattern-mini-chart" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">
      <line x1="0" y1="${thresholdY.toFixed(2)}" x2="${W}" y2="${thresholdY.toFixed(2)}"
        stroke="currentColor" stroke-width="0.6" stroke-dasharray="3 3" opacity="0.4" />
      <polyline points="${points}" fill="none" stroke="currentColor" stroke-width="1.6" />
    </svg>
  `;
}

function prettyDim(dimId) {
  return String(dimId || "")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatTime(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}
function encodeAttr(value) {
  return String(value ?? "").replace(/"/g, "&quot;");
}
