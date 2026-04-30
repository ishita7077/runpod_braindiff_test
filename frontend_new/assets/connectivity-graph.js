/**
 * Connectivity Map — vanilla SVG renderer for the 7-system network graph.
 *
 * Reads `meta.media_features.connectivity` (worker output) and renders:
 *   - Two side-by-side network graphs (A and B) when both are present,
 *     each with 7 nodes arranged in a circle, edges drawn between pairs
 *     with |correlation| ≥ 0.30, edge thickness = abs(corr), edge color
 *     = green (positive) or red-orange (negative).
 *   - Toggleable "Δ delta" view: single network where edges show B-A
 *     change in correlation, with the top-3 most-changed pairs annotated.
 *   - Network metrics panel under each graph.
 *
 * Interactions:
 *   - Hover an edge → tooltip with the exact correlation value
 *   - Hover a node → highlight its incident edges
 *
 * Cream-theme styling. No D3 — pure SVG with manual layout.
 */

const NODE_RADIUS_BASE = 14;
const GRAPH_VIEWBOX = 320;        // square viewport
const CENTER = GRAPH_VIEWBOX / 2;
const CIRCLE_RADIUS = 110;        // distance from center to each node
const EDGE_MIN_PX = 1.4;
const EDGE_MAX_PX = 6.0;

function $(sel, root = document) { return root.querySelector(sel); }

function nodePosition(index, total) {
  // Place node 0 at the top, then go clockwise. Math: angle starts at -π/2.
  const angle = (-Math.PI / 2) + (2 * Math.PI * index) / total;
  return {
    x: CENTER + CIRCLE_RADIUS * Math.cos(angle),
    y: CENTER + CIRCLE_RADIUS * Math.sin(angle),
  };
}

function edgeWidthPx(absWeight) {
  const w = Math.max(0, Math.min(1, absWeight));
  return EDGE_MIN_PX + (EDGE_MAX_PX - EDGE_MIN_PX) * w;
}

function edgeColor(correlation, options = {}) {
  if (options.deltaMode) {
    return correlation >= 0 ? "var(--accent, #c1272d)" : "var(--good, #2a5583)";
  }
  return correlation >= 0 ? "var(--good, #2a5583)" : "var(--accent, #c1272d)";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

function prettyKey(key) {
  return String(key || "")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

/**
 * Build one SVG graph for a single side (or for the delta).
 *
 * @param {Object} payload - the connectivity object: {dim_keys, labels, regions, matrix, edges, metrics, warnings}
 * @param {Object} options - {deltaMode: bool, deltaTopChanged: array|null}
 */
function buildGraphSVG(payload, options = {}) {
  const keys = payload.dim_keys || [];
  if (!keys.length) {
    return `<div class="connectivity-empty">${escapeHtml((payload.warnings && payload.warnings[0]) || "No connectivity data.")}</div>`;
  }
  const labels = payload.labels || keys;
  const total = keys.length;
  const positions = keys.map((_, i) => nodePosition(i, total));
  const edges = payload.edges || [];
  const perNodeStrength = (payload.metrics && payload.metrics.per_node_strength) || {};
  // Maximum strength so we can size nodes proportionally without losing
  // a reasonable minimum. Min = base radius, max = base × 1.7.
  const maxStrength = Math.max(0.0001, ...keys.map((k) => perNodeStrength[k] || 0));

  const edgesSVG = edges
    .map((e) => {
      const i = keys.indexOf(e.source);
      const j = keys.indexOf(e.target);
      if (i < 0 || j < 0) return "";
      const a = positions[i];
      const b = positions[j];
      const w = edgeWidthPx(e.weight);
      const col = edgeColor(e.correlation, options);
      const corrStr = (typeof e.correlation === "number" ? e.correlation : 0).toFixed(2);
      const deltaStr = options.deltaMode ? `Δ ${corrStr}` : `r = ${corrStr}`;
      return `
        <line
          class="conn-edge ${e.type === 'negative' ? 'neg' : 'pos'}"
          x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
          stroke="${col}" stroke-width="${w}" stroke-linecap="round"
          opacity="${0.45 + 0.45 * e.weight}"
          data-source="${escapeHtml(e.source)}"
          data-target="${escapeHtml(e.target)}"
          data-corr="${corrStr}"
          data-label="${escapeHtml(deltaStr)}"
        />
      `;
    })
    .join("");

  const nodesSVG = keys
    .map((key, i) => {
      const p = positions[i];
      const strength = perNodeStrength[key] || 0;
      const r = NODE_RADIUS_BASE * (1 + 0.7 * (strength / maxStrength));
      const isHub = payload.metrics && payload.metrics.hub_node === key;
      const isIsolated = payload.metrics && payload.metrics.isolated_node === key;
      const cls = ["conn-node"];
      if (isHub) cls.push("is-hub");
      if (isIsolated) cls.push("is-iso");
      // Label position: pushed outward from the node so it doesn't overlap.
      const angle = Math.atan2(p.y - CENTER, p.x - CENTER);
      const lx = p.x + Math.cos(angle) * (r + 14);
      const ly = p.y + Math.sin(angle) * (r + 14);
      // Anchor the text based on which half of the circle it's on.
      const anchor =
        Math.cos(angle) > 0.3 ? "start" :
        Math.cos(angle) < -0.3 ? "end" : "middle";
      return `
        <g class="${cls.join(' ')}" data-key="${escapeHtml(key)}">
          <circle cx="${p.x}" cy="${p.y}" r="${r.toFixed(2)}" />
          <text x="${lx.toFixed(2)}" y="${ly.toFixed(2)}" text-anchor="${anchor}" dominant-baseline="middle">${escapeHtml(labels[i] || prettyKey(key))}</text>
        </g>
      `;
    })
    .join("");

  return `
    <svg class="conn-svg" viewBox="0 0 ${GRAPH_VIEWBOX} ${GRAPH_VIEWBOX}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Connectivity graph">
      <g class="conn-edges">${edgesSVG}</g>
      <g class="conn-nodes">${nodesSVG}</g>
    </svg>
  `;
}

function buildMetricsPanel(payload, sideLabel) {
  const m = payload.metrics || {};
  const integration = (m.integration_score || 0).toFixed(2);
  const parallel = (m.parallel_score || 0).toFixed(2);
  const hub = m.hub_node ? prettyKey(m.hub_node) : "—";
  const iso = m.isolated_node ? prettyKey(m.isolated_node) : "—";
  const nT = m.n_timesteps || 0;
  const integrationLabel = (() => {
    const v = parseFloat(integration);
    if (v >= 0.45) return "high integration";
    if (v >= 0.25) return "moderate integration";
    return "low integration";
  })();
  const interpretation = (() => {
    const v = parseFloat(integration);
    const p = parseFloat(parallel);
    if (v >= 0.45 && p > -0.15) return `${sideLabel} integrates the seven systems tightly — when one engages, others tend to engage with it.`;
    if (v < 0.25 && p < -0.20) return `${sideLabel} processes the seven systems in parallel — emotion and reasoning move independently or in opposition.`;
    return `${sideLabel} sits between integrated and parallel — some systems coordinate, others run independently.`;
  })();
  const warnings = (payload.warnings || []).map((w) => `<li>${escapeHtml(w)}</li>`).join("");
  return `
    <div class="conn-metrics">
      <div class="conn-metric">
        <span class="kicker">Integration</span>
        <strong>${integration}</strong>
        <span class="muted">${integrationLabel}</span>
      </div>
      <div class="conn-metric">
        <span class="kicker">Parallel score</span>
        <strong>${parallel}</strong>
        <span class="muted">mean of negative edges</span>
      </div>
      <div class="conn-metric">
        <span class="kicker">Hub</span>
        <strong>${escapeHtml(hub)}</strong>
        <span class="muted">most-coupled system</span>
      </div>
      <div class="conn-metric">
        <span class="kicker">Isolated</span>
        <strong>${escapeHtml(iso)}</strong>
        <span class="muted">least-coupled system</span>
      </div>
      <div class="conn-metric">
        <span class="kicker">Timesteps</span>
        <strong>${nT}</strong>
        <span class="muted">per-second activations</span>
      </div>
    </div>
    <p class="conn-interpretation">${escapeHtml(interpretation)}</p>
    ${warnings ? `<ul class="conn-warnings">${warnings}</ul>` : ""}
  `;
}

function buildDeltaPanel(deltaPayload, payloadA, payloadB) {
  const top = deltaPayload.top_changed || [];
  if (!top.length) return "";
  const items = top
    .slice(0, 3)
    .map((d) => {
      const dir = d.delta > 0 ? "tighter in B" : "tighter in A";
      return `
        <li>
          <strong>${escapeHtml(prettyKey(d.source))} ↔ ${escapeHtml(prettyKey(d.target))}</strong>
          <span class="muted">${dir} by Δ ${d.delta.toFixed(2)}</span>
        </li>
      `;
    })
    .join("");
  return `
    <div class="conn-delta-list">
      <div class="kicker">Most-changed pairs</div>
      <ol>${items}</ol>
    </div>
  `;
}

/**
 * Mount the connectivity section into `root`.
 *
 * @param {HTMLElement} root
 * @param {Object} connectivity - the meta.media_features.connectivity payload
 * @param {{labelA: string, labelB: string}} opts
 */
export function renderConnectivity(root, connectivity, opts = {}) {
  if (!root) return;
  if (!connectivity || (!connectivity.a && !connectivity.b)) {
    root.innerHTML = `<div class="connectivity-empty">Connectivity map not available for this run.</div>`;
    return;
  }
  const labelA = opts.labelA || "Version A";
  const labelB = opts.labelB || "Version B";

  const sideA = connectivity.a || {};
  const sideB = connectivity.b || {};

  // Decide if we have both sides and the delta — if so, mount a mode toggle.
  const hasBoth = (sideA.dim_keys || []).length > 0 && (sideB.dim_keys || []).length > 0;

  root.innerHTML = `
    <div class="connectivity-head">
      <p class="micro">Cortical connectivity</p>
      <h2>How the seven systems coordinated</h2>
      <p class="connectivity-sub">
        Each line is the Pearson correlation between two systems' per-second activations.
        Thick line = always engaged together. Slate-blue = together, vermillion = in opposition.
        Threshold: |r| ≥ 0.30. Population-average prediction from TRIBE v2; not raw fMRI.
        <a href="/methodology/connectivity">How we compute this →</a>
      </p>
      ${hasBoth ? `
        <div class="connectivity-mode-toggle" role="tablist" aria-label="Connectivity view mode">
          <button class="conn-mode-btn is-active" data-mode="side_by_side" type="button">Side by side</button>
          <button class="conn-mode-btn" data-mode="delta" type="button">Δ B − A</button>
        </div>
      ` : ""}
    </div>
    <div class="connectivity-body">
      <div class="connectivity-pair" data-pair-mode="side_by_side">
        <div class="connectivity-card">
          <div class="connectivity-card-head"><span class="badge a">A</span> ${escapeHtml(labelA)}</div>
          ${buildGraphSVG(sideA)}
          ${buildMetricsPanel(sideA, labelA)}
        </div>
        <div class="connectivity-card">
          <div class="connectivity-card-head"><span class="badge b">B</span> ${escapeHtml(labelB)}</div>
          ${buildGraphSVG(sideB)}
          ${buildMetricsPanel(sideB, labelB)}
        </div>
      </div>
      ${connectivity.delta && hasBoth ? `
        <div class="connectivity-delta" data-pair-mode="delta" hidden>
          <div class="connectivity-card">
            <div class="connectivity-card-head"><span class="badge delta">Δ</span> Connectivity change (B − A)</div>
            ${buildGraphSVG(deltaToGraphPayload(connectivity.delta, sideA, sideB), { deltaMode: true })}
            ${buildDeltaPanel(connectivity.delta, sideA, sideB)}
          </div>
        </div>
      ` : ""}
      <div class="connectivity-tooltip" id="connTooltip" hidden></div>
    </div>
  `;

  wireInteractions(root);
  wireModeToggle(root);
}

function deltaToGraphPayload(delta, sideA, sideB) {
  // Convert the symmetric delta matrix into a graph payload the same
  // SVG builder can render. Edges where |delta| ≥ 0.10 (smaller than
  // the absolute correlation threshold because deltas are typically
  // smaller in magnitude).
  const keys = sideA.dim_keys || [];
  const labels = sideA.labels || [];
  const matrix = delta.matrix || [];
  const edges = [];
  for (let i = 0; i < keys.length; i += 1) {
    for (let j = i + 1; j < keys.length; j += 1) {
      const d = matrix[i] && matrix[i][j];
      if (typeof d !== "number") continue;
      if (Math.abs(d) >= 0.10) {
        edges.push({
          source: keys[i],
          target: keys[j],
          weight: Math.min(1, Math.abs(d) * 1.5),
          correlation: d,
          type: d >= 0 ? "positive" : "negative",
        });
      }
    }
  }
  edges.sort((a, b) => b.weight - a.weight);
  return {
    dim_keys: keys,
    labels,
    regions: sideA.regions || [],
    matrix,
    edges,
    metrics: { per_node_strength: {} },
    warnings: [],
  };
}

function wireModeToggle(root) {
  const buttons = root.querySelectorAll(".conn-mode-btn");
  const sideBySide = root.querySelector('[data-pair-mode="side_by_side"]');
  const delta = root.querySelector('[data-pair-mode="delta"]');
  if (!buttons.length || !sideBySide) return;
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.toggle("is-active", b === btn));
      const mode = btn.dataset.mode;
      if (mode === "delta" && delta) {
        sideBySide.hidden = true;
        delta.hidden = false;
      } else {
        sideBySide.hidden = false;
        if (delta) delta.hidden = true;
      }
    });
  });
}

function wireInteractions(root) {
  const tooltip = root.querySelector("#connTooltip");
  // Edge hover: show exact correlation.
  root.querySelectorAll(".conn-edge").forEach((edge) => {
    edge.addEventListener("mousemove", (e) => {
      const label = edge.getAttribute("data-label") || "";
      const source = prettyKey(edge.getAttribute("data-source") || "");
      const target = prettyKey(edge.getAttribute("data-target") || "");
      tooltip.innerHTML = `<strong>${source} ↔ ${target}</strong><span>${label}</span>`;
      tooltip.hidden = false;
      const rect = root.getBoundingClientRect();
      tooltip.style.left = `${e.clientX - rect.left + 12}px`;
      tooltip.style.top = `${e.clientY - rect.top + 12}px`;
      edge.classList.add("is-hot");
    });
    edge.addEventListener("mouseleave", () => {
      tooltip.hidden = true;
      edge.classList.remove("is-hot");
    });
  });
  // Node hover: highlight incident edges.
  root.querySelectorAll(".conn-node").forEach((node) => {
    const key = node.getAttribute("data-key");
    node.addEventListener("mouseenter", () => {
      root.querySelectorAll(".conn-edge").forEach((edge) => {
        const incident =
          edge.getAttribute("data-source") === key ||
          edge.getAttribute("data-target") === key;
        edge.classList.toggle("is-fade", !incident);
        edge.classList.toggle("is-incident", incident);
      });
    });
    node.addEventListener("mouseleave", () => {
      root.querySelectorAll(".conn-edge").forEach((edge) => {
        edge.classList.remove("is-fade");
        edge.classList.remove("is-incident");
      });
    });
  });
}
