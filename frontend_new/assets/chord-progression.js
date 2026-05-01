/**
 * Cortical Chord Progression — Brain Diff novel feature.
 *
 * A "chord" is the cortical state at one second: which combination of the
 * seven Yeo-network systems are co-active above their per-clip threshold.
 * A video's progression from one chord to the next is its cognitive grammar.
 *
 * THRESHOLD APPROACH (v2 — clip-relative percentiles)
 * Earlier versions used absolute thresholds (0.55, 0.50…). Those numbers had
 * no neuroscientific anchor — they were UX heuristics derived from synthetic
 * fixtures. Cognitive neuroscience almost universally uses *distribution-
 * relative* thresholds (median splits, quartile splits, z-scores against the
 * study's own data — Falk 2012 used a median split). We do the same.
 *
 *   - HIGH threshold per system = 70th percentile of THAT system's own
 *     activation values within THIS clip
 *   - LOW threshold per system  = 30th percentile of the same
 *   - SOFT threshold (used by Story Integration's third role) = 50th (median)
 *
 * A "Learning Moment" therefore fires at second t when both Attention AND
 * Memory Encoding are simultaneously in their respective top quartiles in
 * this video — the same shape of claim Falk made for mPFC.
 *
 * Sustain is 1s for most chords (hemodynamic response width is ~4–6s, so
 * sub-second precision is not meaningful anyway). Longer sustain is kept for
 * Story Integration and Cold Cognitive Work where transient firing is not
 * the construct of interest.
 *
 * Diag mode: append `?diag=1` to the URL to get a panel above the chord
 * progression with per-system distribution stats and per-chord fire counts.
 *
 * Inputs:
 *   - dimensions: result.dimensions[] from the worker
 *     ({key, label, region, timeseries_a:number[], timeseries_b:number[]})
 *   - durationA / durationB: total seconds per side
 *
 * Outputs (per side): array of {chord, startSec, endSec, intensity}
 */

const PERCENTILE_HIGH = 0.70;
const PERCENTILE_LOW  = 0.30;
const PERCENTILE_SOFT = 0.50;

// ─── Role mapping ───────────────────────────────────────────────────────────
// Match by key OR label substring (case-insensitive). Robust to API rename.
const ROLE_PATTERNS = [
  { role: "attention",  patterns: ["attention", "salience"] },
  { role: "memory",     patterns: ["memory", "encoding", "vlpfc"] },
  { role: "personal",   patterns: ["personal", "resonance", "self", "mpfc"] },
  { role: "gut",        patterns: ["gut", "visceral", "insula", "interocep"] },
  { role: "effort",     patterns: ["effort", "control", "dlpfc", "executive"] },
  { role: "language",   patterns: ["language", "broca", "wernicke", "linguistic"] },
  { role: "social",     patterns: ["social", "tpj", "mentaliz", "theory"] },
];

function roleOf(dim) {
  const haystack = (String(dim.key || "") + " " + String(dim.label || "")).toLowerCase();
  for (const { role, patterns } of ROLE_PATTERNS) {
    if (patterns.some((p) => haystack.includes(p))) return role;
  }
  return null;
}

function rolesByDimension(dimensions) {
  const map = {};
  for (const d of dimensions) {
    const r = roleOf(d);
    if (r && !map[r]) map[r] = d;
  }
  return map;
}

// ─── Chord definitions ──────────────────────────────────────────────────────
// Each rule receives (rolesAtSecond, thresholds) and returns {fires, intensity}.
// Threshold object shape: { attention: {high, low, soft}, memory: {...}, … }
export const CHORDS = [
  {
    key: "learning_moment",
    name: "Learning Moment",
    blurb: "Attention + Memory Encoding both in their top quartile.",
    science:
      "Wagner 1998 (subsequent-memory effect) + Corbetta & Shulman 2002 (DAN). " +
      "When DAN and left vlPFC co-fire, content has the cortical signature of " +
      "events more likely to be remembered.",
    minSec: 1,
    color: "var(--chord-learning, #b38a30)", // gold
    rule: (r, T) =>
      hasAll(r, ["attention", "memory"]) &&
      r.attention >= T.attention.high && r.memory >= T.memory.high
        ? { intensity: avg(r.attention, r.memory), fires: true }
        : { fires: false },
  },
  {
    key: "emotional_impact",
    name: "Emotional Impact",
    blurb: "Personal Resonance + Gut Reaction both in their top quartile.",
    science:
      "Falk 2012 (mPFC predicts population behaviour, r=0.87) + Critchley 2005 " +
      "(anterior insula = visceral cortex). mPFC-insula co-activation is the " +
      "cortical correlate of content that doesn't just inform but lands.",
    minSec: 1,
    color: "var(--chord-emotional, #c1272d)", // accent red
    rule: (r, T) =>
      hasAll(r, ["personal", "gut"]) &&
      r.personal >= T.personal.high && r.gut >= T.gut.high
        ? { intensity: avg(r.personal, r.gut), fires: true }
        : { fires: false },
  },
  {
    key: "reasoning_beat",
    name: "Reasoning Beat",
    blurb: "Brain Effort + Language both in their top quartile.",
    science:
      "Miller & Cohen 2001 (dlPFC = cognitive control) + Fedorenko 2011 " +
      "(language network specificity). The viewer is working through meaning, " +
      "not passively receiving language.",
    minSec: 1,
    color: "var(--chord-reasoning, #6a97c9)", // cool blue
    rule: (r, T) =>
      hasAll(r, ["effort", "language"]) &&
      r.effort >= T.effort.high && r.language >= T.language.high
        ? { intensity: avg(r.effort, r.language), fires: true }
        : { fires: false },
  },
  {
    key: "story_integration",
    name: "Story Integration",
    blurb:
      "Attention + Language in top quartile, Personal Resonance above its median.",
    science:
      "Mar 2011 (DMN in narrative) + Hasson 2008 (inter-subject sync). " +
      "Three-way conjunction means the viewer isn't just tracking words, " +
      "they're building a model of what the content means.",
    minSec: 2,
    color: "var(--chord-story, #8a6820)", // deep gold
    rule: (r, T) =>
      hasAll(r, ["attention", "language", "personal"]) &&
      r.attention >= T.attention.high && r.language >= T.language.high &&
      r.personal >= T.personal.soft
        ? { intensity: avg(r.attention, r.language, r.personal), fires: true }
        : { fires: false },
  },
  {
    key: "visceral_hit",
    name: "Visceral Hit",
    blurb: "Gut in top quartile while Brain Effort sits in its bottom quartile.",
    science:
      "Critchley 2005 + Fox 2005 (task-positive / DMN anti-correlation) + " +
      "Damasio's somatic marker. Pre-reflective insula response without " +
      "dlPFC's cognitive check.",
    minSec: 1,
    color: "var(--chord-visceral, #e25b43)", // coral
    rule: (r, T) =>
      hasAll(r, ["gut", "effort"]) &&
      r.gut >= T.gut.high && r.effort <= T.effort.low
        ? { intensity: r.gut, fires: true }
        : { fires: false },
  },
  {
    key: "cold_cognitive",
    name: "Cold Cognitive Work",
    blurb:
      "Brain Effort in top quartile while Personal Resonance sits in its bottom quartile.",
    science:
      "Fox 2005 (task-positive vs DMN anti-correlation) + Raichle 2001 " +
      "(default mode). The cortex is doing the work; the self-relevance " +
      "tag is suppressed.",
    minSec: 2,
    color: "var(--chord-cold, #5a5a6a)", // muted slate
    rule: (r, T) =>
      hasAll(r, ["effort", "personal"]) &&
      r.effort >= T.effort.high && r.personal <= T.personal.low
        ? { intensity: r.effort, fires: true }
        : { fires: false },
  },
  {
    key: "social_resonance",
    name: "Social Resonance",
    blurb: "Social Thinking + Personal Resonance both in their top quartile.",
    science:
      "Saxe & Kanwisher 2003 (rTPJ = theory of mind) + Mar 2011. " +
      "Modeling another mind through the lens of one's own — the cortical " +
      "shape of empathy.",
    minSec: 1,
    color: "var(--chord-social, #B89BC9)", // soft purple
    rule: (r, T) =>
      hasAll(r, ["social", "personal"]) &&
      r.social >= T.social.high && r.personal >= T.personal.high
        ? { intensity: avg(r.social, r.personal), fires: true }
        : { fires: false },
  },
];

const CHORDS_BY_KEY = Object.fromEntries(CHORDS.map((c) => [c.key, c]));

// ─── Stats helpers ─────────────────────────────────────────────────────────
function hasAll(roles, names) {
  return names.every((n) => Number.isFinite(roles[n]));
}
function avg(...xs) {
  const v = xs.filter((n) => Number.isFinite(n));
  return v.length ? v.reduce((s, n) => s + n, 0) / v.length : 0;
}
function percentile(values, p) {
  const arr = (Array.isArray(values) ? values : [])
    .map(Number)
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  if (!arr.length) return 0;
  // Linear interpolation between the two surrounding ranks.
  const rank = p * (arr.length - 1);
  const lo = Math.floor(rank);
  const hi = Math.ceil(rank);
  if (lo === hi) return arr[lo];
  return arr[lo] + (arr[hi] - arr[lo]) * (rank - lo);
}
function summaryStats(values) {
  const arr = (Array.isArray(values) ? values : [])
    .map(Number)
    .filter(Number.isFinite);
  if (!arr.length) return { n: 0, min: 0, max: 0, mean: 0, p30: 0, p50: 0, p70: 0 };
  return {
    n: arr.length,
    min: Math.min(...arr),
    max: Math.max(...arr),
    mean: arr.reduce((s, x) => s + x, 0) / arr.length,
    p30: percentile(arr, PERCENTILE_LOW),
    p50: percentile(arr, PERCENTILE_SOFT),
    p70: percentile(arr, PERCENTILE_HIGH),
  };
}
/** Sample a value from a time series at fractional position 0..1. */
function sampleAt(series, frac) {
  if (!Array.isArray(series) || series.length === 0) return null;
  const i = Math.max(0, Math.min(series.length - 1, Math.round(frac * (series.length - 1))));
  const v = Number(series[i]);
  return Number.isFinite(v) ? v : null;
}

// ─── Threshold builder (per side, per role) ────────────────────────────────
function buildThresholds(roles, side) {
  const T = {};
  const field = side === "b" ? "timeseries_b" : "timeseries_a";
  for (const role of Object.keys(roles)) {
    const ts = roles[role][field] || [];
    T[role] = {
      high: percentile(ts, PERCENTILE_HIGH),
      low:  percentile(ts, PERCENTILE_LOW),
      soft: percentile(ts, PERCENTILE_SOFT),
      stats: summaryStats(ts),
    };
  }
  return T;
}

/**
 * Classify chords for one side. Returns {events, thresholds, secValues}.
 * - events: per-chord ranges with the per-chord minSec gate applied
 * - thresholds: the per-role percentile thresholds used
 * - secValues: the per-second role-value snapshots (for diag mode)
 */
export function classifyChords(dimensions, durationSec, side) {
  const dur = Math.max(1, Math.round(durationSec || 0));
  const roles = rolesByDimension(dimensions);
  const field = side === "b" ? "timeseries_b" : "timeseries_a";
  const T = buildThresholds(roles, side);

  // Build per-second role values.
  const secValues = []; // [ {attention, memory, ...}, ... ] length = dur
  for (let s = 0; s < dur; s += 1) {
    const frac = s / Math.max(1, dur - 1);
    const r = {};
    for (const role of Object.keys(roles)) {
      const v = sampleAt(roles[role][field], frac);
      if (v !== null) r[role] = v;
    }
    secValues.push(r);
  }

  // Per-chord run detection — coalesce consecutive seconds into ranges.
  const events = [];
  for (const def of CHORDS) {
    let runStart = -1;
    let runIntensities = [];
    for (let s = 0; s < dur; s += 1) {
      const out = def.rule(secValues[s], T);
      if (out.fires) {
        if (runStart === -1) runStart = s;
        runIntensities.push(Number(out.intensity) || 0);
      } else if (runStart !== -1) {
        const len = s - runStart;
        if (len >= def.minSec) {
          events.push({
            chord: def.key,
            startSec: runStart,
            endSec: s,
            intensity: avg(...runIntensities),
          });
        }
        runStart = -1;
        runIntensities = [];
      }
    }
    if (runStart !== -1) {
      const len = dur - runStart;
      if (len >= def.minSec) {
        events.push({
          chord: def.key,
          startSec: runStart,
          endSec: dur,
          intensity: avg(...runIntensities),
        });
      }
    }
  }

  events.sort((a, b) => a.startSec - b.startSec || a.endSec - b.endSec);
  return { events, thresholds: T, secValues, durationSec: dur };
}

// ─── Progression descriptors ───────────────────────────────────────────────
/**
 * Compute per-chord coverage (seconds & % of clip) and the dominant chord.
 * Returns { coverage: [{chord, sec, pct}], dominant: chord_key|null }
 */
function chordCoverage(events, durationSec) {
  const total = Math.max(1, durationSec || 0);
  const by = {};
  for (const e of events) {
    const span = e.endSec - e.startSec;
    by[e.chord] = (by[e.chord] || 0) + span;
  }
  const coverage = Object.entries(by)
    .map(([chord, sec]) => ({ chord, sec, pct: sec / total }))
    .sort((a, b) => b.sec - a.sec);
  return { coverage, dominant: coverage[0]?.chord || null };
}

/**
 * Build a sequence summary like:
 *   "Reasoning Beat (38% of clip) dominates.
 *    Sequence: Visceral Hit → Reasoning Beat → Emotional Impact"
 * Or, when no chord fires in this clip:
 *   "All systems below their own top quartile — the cortex stayed flat."
 */
export function progressionString(events, durationSec) {
  if (!events.length) {
    return "All seven systems stayed below their own top quartile here — the cortex did not lock into any of the named co-activation patterns in this clip.";
  }
  const { coverage, dominant } = chordCoverage(events, durationSec);
  const dominantName = (CHORDS_BY_KEY[dominant] && CHORDS_BY_KEY[dominant].name) || dominant;
  const dominantPct = Math.round((coverage[0].pct || 0) * 100);

  // Walk events in chronological order; collapse adjacent identical chords.
  const seq = [];
  for (const e of events) {
    if (!seq.length || seq[seq.length - 1] !== e.chord) seq.push(e.chord);
  }
  const trimmed = seq.length > 6 ? seq.slice(0, 6).concat(["…"]) : seq;
  const sequence = trimmed
    .map((k) => (k === "…" ? "…" : (CHORDS_BY_KEY[k] && CHORDS_BY_KEY[k].name) || k))
    .join("  →  ");

  return `${dominantName} dominates (${dominantPct}% of clip). Sequence: ${sequence}.`;
}

// ─── Renderer ──────────────────────────────────────────────────────────────

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}
function fmtSec(s) {
  const n = Math.max(0, Math.round(s));
  return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;
}
function fmt2(x) {
  return Number.isFinite(x) ? x.toFixed(2) : "—";
}
function diagEnabled() {
  try {
    return new URLSearchParams(location.search).get("diag") === "1";
  } catch (_) { return false; }
}

/**
 * Render the chord progression panel into `root`.
 * Returns true if it rendered, false if there isn't enough data.
 */
export function renderChordProgression(root, opts) {
  if (!root) return false;
  const {
    dimensions = [],
    durationA = 0,
    durationB = 0,
    labelA = "Cut A",
    labelB = "Cut B",
  } = opts || {};

  if (!dimensions.length) {
    root.hidden = true;
    return false;
  }

  // Need at least two named systems to evaluate any chord rule.
  const presentRoles = new Set();
  for (const d of dimensions) {
    const r = roleOf(d);
    if (r) presentRoles.add(r);
  }
  if (presentRoles.size < 2) {
    root.hidden = true;
    return false;
  }

  const A = classifyChords(dimensions, durationA || 30, "a");
  const B = classifyChords(dimensions, durationB || 30, "b");

  const totalA = Math.max(durationA || 30, 1);
  const totalB = Math.max(durationB || 30, 1);
  const totalMax = Math.max(totalA, totalB);

  const showDiag = diagEnabled();

  root.hidden = false;
  root.innerHTML = `
    <div class="chord-head">
      <p class="micro">A second-by-second cognitive grammar</p>
      <h3>What chord is the cortex playing?</h3>
      <p class="chord-sub">
        At every second, certain combinations of the seven systems fire together.
        That combination is a <strong>chord</strong>. The progression from one
        chord to the next is the <em>cognitive grammar</em> of the content.
        Hover any block for the science behind it.
      </p>
    </div>

    ${showDiag ? renderDiagPanel(A, B, labelA, labelB, dimensions) : ""}

    <div class="chord-progression-pair">
      ${renderSide(labelA, "a", A, totalA, totalMax)}
      ${renderSide(labelB, "b", B, totalB, totalMax)}
    </div>

    <details class="chord-details">
      <summary>The seven chords — formulas, science, citations ↓</summary>
      <div class="chord-defs-grid">
        ${CHORDS.map(renderChordCard).join("")}
      </div>
      <p class="chord-fineprint">
        <strong>Threshold method:</strong> per clip, each system's threshold is set
        to the <strong>70th percentile</strong> of its own activation values
        within that clip (low-quartile inverse rules use the 30th). A chord
        fires when the required systems are simultaneously in their respective
        top (or bottom) quartile, sustained for the chord's minimum window.
        TRIBE v2 outputs are not calibrated to a fixed neuroscientific scale,
        so absolute cross-clip thresholds aren't used. This is the same
        median-split logic Falk 2012 used to predict population-level
        behaviour from mPFC. See <a href="/research">/research</a> for context.
        Append <code>?diag=1</code> to this URL to see the per-system
        distribution stats and threshold values.
      </p>
    </details>
  `;

  // Hover tooltip — show the chord name and time on hover of any block.
  root.querySelectorAll(".chord-block").forEach((node) => {
    node.addEventListener("mouseenter", () => node.classList.add("is-hover"));
    node.addEventListener("mouseleave", () => node.classList.remove("is-hover"));
  });

  if (showDiag) {
    // Also dump full diagnostic to the console for share / debugging.
    // eslint-disable-next-line no-console
    console.groupCollapsed("[chord-progression] diag");
    console.log("dimensions input", dimensions);
    console.log("A side classification", A);
    console.log("B side classification", B);
    console.groupEnd();
  }

  return true;
}

function renderSide(label, side, classified, dur, totalMax) {
  const events = classified.events;
  const widthPct = (dur / totalMax) * 100;
  const blocks = events
    .map((e) => {
      const def = CHORDS_BY_KEY[e.chord];
      if (!def) return "";
      const left = (e.startSec / dur) * 100;
      const width = ((e.endSec - e.startSec) / dur) * 100;
      const tip = `${def.name} · ${fmtSec(e.startSec)}–${fmtSec(e.endSec)} · ${def.blurb}`;
      return `<span class="chord-block" data-chord="${escapeHtml(def.key)}"
                style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%;background:${def.color}"
                title="${escapeHtml(tip)}"
                aria-label="${escapeHtml(tip)}">
                <span class="chord-block-label">${escapeHtml(def.name)}</span>
              </span>`;
    })
    .join("");
  const progression = progressionString(events, dur);
  const summary = events.length
    ? `${events.length} chord event${events.length === 1 ? "" : "s"} across ${fmtSec(dur)}`
    : `${fmtSec(dur)} clip · all systems below their top quartile`;
  return `
    <div class="chord-side chord-side-${side}">
      <div class="chord-side-head">
        <span class="badge ${side}">${side.toUpperCase()}</span>
        <span class="chord-side-name">${escapeHtml(label)}</span>
        <span class="chord-side-meta">${escapeHtml(summary)}</span>
      </div>
      <div class="chord-strip-wrap" style="--strip-w:${widthPct.toFixed(2)}%">
        <div class="chord-strip" role="img" aria-label="Chord progression for ${escapeHtml(label)}">
          <div class="chord-strip-axis">
            ${axisTicks(dur)}
          </div>
          <div class="chord-strip-blocks">${blocks || `<div class="chord-empty">No chords above clip-relative threshold</div>`}</div>
        </div>
      </div>
      <p class="chord-progression-line">
        <strong>Progression:</strong> ${escapeHtml(progression)}
      </p>
    </div>
  `;
}

function axisTicks(dur) {
  const N = 5;
  const out = [];
  for (let i = 0; i < N; i += 1) {
    const t = (i / (N - 1)) * dur;
    const left = (i / (N - 1)) * 100;
    out.push(`<span class="chord-tick" style="left:${left}%">${fmtSec(t)}</span>`);
  }
  return out.join("");
}

function renderChordCard(def) {
  return `
    <article class="chord-def-card">
      <div class="chord-def-head">
        <span class="chord-def-swatch" style="background:${def.color}"></span>
        <h4>${escapeHtml(def.name)}</h4>
      </div>
      <p class="chord-def-blurb">${escapeHtml(def.blurb)}</p>
      <p class="chord-def-science">${escapeHtml(def.science)}</p>
      <p class="chord-def-meta">Min duration: ${def.minSec}s</p>
    </article>
  `;
}

// ─── ?diag=1 panel ─────────────────────────────────────────────────────────
function renderDiagPanel(A, B, labelA, labelB, dimensions) {
  const allRoles = Array.from(
    new Set([...Object.keys(A.thresholds), ...Object.keys(B.thresholds)])
  );
  const fireCount = (events, k) => events.filter((e) => e.chord === k).length;

  const rolesRows = allRoles
    .map((role) => {
      const a = A.thresholds[role]?.stats || {};
      const b = B.thresholds[role]?.stats || {};
      return `<tr>
        <td>${escapeHtml(role)}</td>
        <td>${a.n || 0} / ${b.n || 0}</td>
        <td>${fmt2(a.min)} / ${fmt2(b.min)}</td>
        <td>${fmt2(a.max)} / ${fmt2(b.max)}</td>
        <td>${fmt2(a.mean)} / ${fmt2(b.mean)}</td>
        <td><strong>${fmt2(a.p30)} / ${fmt2(b.p30)}</strong></td>
        <td><strong>${fmt2(a.p50)} / ${fmt2(b.p50)}</strong></td>
        <td><strong>${fmt2(a.p70)} / ${fmt2(b.p70)}</strong></td>
      </tr>`;
    })
    .join("");

  const chordsRows = CHORDS
    .map((def) => `<tr>
      <td><span class="chord-diag-swatch" style="background:${def.color}"></span> ${escapeHtml(def.name)}</td>
      <td>${fireCount(A.events, def.key)} / ${fireCount(B.events, def.key)}</td>
      <td>min ${def.minSec}s</td>
    </tr>`)
    .join("");

  const presentDims = dimensions
    .map((d) => `${escapeHtml(d.label || d.key || "?")} → ${escapeHtml(roleOf(d) || "(unmapped)")}`)
    .join(", ");

  return `
    <div class="chord-diag">
      <h4>Diagnostic dump <span class="chord-diag-badge">?diag=1</span></h4>
      <p class="chord-diag-sub">
        Per-side stats. Cells show <strong>A / B</strong>. Thresholds for chord
        rules: HIGH = p70, LOW = p30, SOFT = p50, all clip-relative per system.
      </p>
      <p class="chord-diag-sub"><strong>Dimension → role mapping:</strong> ${presentDims}</p>

      <table class="chord-diag-table">
        <thead><tr>
          <th>Role</th><th>n</th><th>min</th><th>max</th><th>mean</th>
          <th>p30 (LOW)</th><th>p50 (SOFT)</th><th>p70 (HIGH)</th>
        </tr></thead>
        <tbody>${rolesRows}</tbody>
      </table>

      <h5>Chord fire counts (A / B)</h5>
      <table class="chord-diag-table">
        <thead><tr><th>Chord</th><th>fires</th><th>sustain</th></tr></thead>
        <tbody>${chordsRows}</tbody>
      </table>
    </div>
  `;
}
