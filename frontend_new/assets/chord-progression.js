/**
 * Cortical Chord Progression — Brain Diff novel feature.
 *
 * A "chord" is the cortical state at one second: which combination of the
 * seven Yeo-network systems are co-active above threshold. A video's
 * progression from one chord to the next is its cognitive grammar.
 *
 * The chord rules below are direct implementations of the formulas in
 * braindiff_chord_progression_science_reference.md. Threshold values are
 * v1 defaults — to be recalibrated as ground-truth data accumulates.
 *
 * Inputs:
 *   - dimensions: result.dimensions[] from the worker
 *     ({key, label, region, timeseries_a:number[], timeseries_b:number[]})
 *   - durationA / durationB: total seconds per side
 *
 * Outputs (per side): array of {chord, startSec, endSec, intensity}
 */

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
// Each rule: returns { intensity, fires } given the seven role values at one
// second. intensity is a 0..1 strength used for visual encoding.
export const CHORDS = [
  {
    key: "learning_moment",
    name: "Learning Moment",
    blurb: "Attention + Memory Encoding → encoded for later recall.",
    science:
      "Wagner 1998 (subsequent-memory effect) + Corbetta & Shulman 2002 (DAN). " +
      "When DAN and left vlPFC co-fire, content has the cortical signature of " +
      "events more likely to be remembered.",
    minSec: 2,
    color: "var(--chord-learning, #b38a30)", // gold
    rule: (r) =>
      hasAll(r, ["attention", "memory"]) && r.attention >= 0.55 && r.memory >= 0.55
        ? { intensity: avg(r.attention, r.memory), fires: true }
        : { fires: false },
  },
  {
    key: "emotional_impact",
    name: "Emotional Impact",
    blurb: "Personal Resonance + Gut Reaction → it landed in the body.",
    science:
      "Falk 2012 (mPFC predicts population behaviour, r=0.87) + Critchley 2005 " +
      "(anterior insula = visceral cortex). mPFC-insula co-activation is the " +
      "cortical correlate of content that doesn't just inform but lands.",
    minSec: 2,
    color: "var(--chord-emotional, #c1272d)", // accent red
    rule: (r) =>
      hasAll(r, ["personal", "gut"]) && r.personal >= 0.55 && r.gut >= 0.55
        ? { intensity: avg(r.personal, r.gut), fires: true }
        : { fires: false },
  },
  {
    key: "reasoning_beat",
    name: "Reasoning Beat",
    blurb: "Brain Effort + Language → actively interpreting, not absorbing.",
    science:
      "Miller & Cohen 2001 (dlPFC = cognitive control) + Fedorenko 2011 " +
      "(language network specificity). The viewer is working through meaning, " +
      "not passively receiving language.",
    minSec: 2,
    color: "var(--chord-reasoning, #6a97c9)", // cool blue
    rule: (r) =>
      hasAll(r, ["effort", "language"]) && r.effort >= 0.5 && r.language >= 0.5
        ? { intensity: avg(r.effort, r.language), fires: true }
        : { fires: false },
  },
  {
    key: "story_integration",
    name: "Story Integration",
    blurb:
      "Attention + Language + Personal — situation modeling, the brain inhabits the story.",
    science:
      "Mar 2011 (DMN in narrative) + Hasson 2008 (inter-subject sync). " +
      "Three-way conjunction means the viewer isn't just tracking words, " +
      "they're building a model of what the content means.",
    minSec: 3,
    color: "var(--chord-story, #8a6820)", // deep gold
    rule: (r) =>
      hasAll(r, ["attention", "language", "personal"]) &&
      r.attention >= 0.5 && r.language >= 0.5 && r.personal >= 0.4
        ? { intensity: avg(r.attention, r.language, r.personal), fires: true }
        : { fires: false },
  },
  {
    key: "visceral_hit",
    name: "Visceral Hit",
    blurb: "Gut high, Brain Effort low — body reacted before the mind did.",
    science:
      "Critchley 2005 + Fox 2005 (task-positive / DMN anti-correlation) + " +
      "Damasio's somatic marker. Pre-reflective insula response without " +
      "dlPFC's cognitive check.",
    minSec: 2,
    color: "var(--chord-visceral, #e25b43)", // coral
    rule: (r) =>
      hasAll(r, ["gut", "effort"]) && r.gut >= 0.55 && r.effort <= 0.4
        ? { intensity: r.gut, fires: true }
        : { fires: false },
  },
  {
    key: "cold_cognitive",
    name: "Cold Cognitive Work",
    blurb: "Effort high, Personal Resonance low — processed but not felt.",
    science:
      "Fox 2005 (task-positive vs DMN anti-correlation) + Raichle 2001 " +
      "(default mode). The cortex is doing the work; the self-relevance " +
      "tag is suppressed.",
    minSec: 3,
    color: "var(--chord-cold, #5a5a6a)", // muted slate
    rule: (r) =>
      hasAll(r, ["effort", "personal"]) && r.effort >= 0.65 && r.personal <= 0.35
        ? { intensity: r.effort, fires: true }
        : { fires: false },
  },
  {
    key: "social_resonance",
    name: "Social Resonance",
    blurb: "Social Thinking + Personal Resonance — empathic connection fires.",
    science:
      "Saxe & Kanwisher 2003 (rTPJ = theory of mind) + Mar 2011. " +
      "Modeling another mind through the lens of one's own — the cortical " +
      "shape of empathy.",
    minSec: 2,
    color: "var(--chord-social, #B89BC9)", // soft purple
    rule: (r) =>
      hasAll(r, ["social", "personal"]) && r.social >= 0.45 && r.personal >= 0.45
        ? { intensity: avg(r.social, r.personal), fires: true }
        : { fires: false },
  },
];

const CHORDS_BY_KEY = Object.fromEntries(CHORDS.map((c) => [c.key, c]));

// ─── Classifier ────────────────────────────────────────────────────────────
function hasAll(roles, names) {
  return names.every((n) => Number.isFinite(roles[n]));
}
function avg(...xs) {
  const v = xs.filter((n) => Number.isFinite(n));
  return v.length ? v.reduce((s, n) => s + n, 0) / v.length : 0;
}

/** Sample a value from a time series at fractional position 0..1. */
function sampleAt(series, frac) {
  if (!Array.isArray(series) || series.length === 0) return null;
  const i = Math.max(0, Math.min(series.length - 1, Math.round(frac * (series.length - 1))));
  const v = Number(series[i]);
  return Number.isFinite(v) ? v : null;
}

/**
 * Classify chords for one side. Returns array of {chord, startSec, endSec,
 * intensity}, with consecutive seconds of the same chord coalesced into
 * ranges and the per-chord minSec gate applied.
 */
export function classifyChords(dimensions, durationSec, side) {
  const dur = Math.max(1, Math.round(durationSec || 0));
  const roles = rolesByDimension(dimensions);
  const field = side === "b" ? "timeseries_b" : "timeseries_a";

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

  // Per second, evaluate every chord rule. Multiple chords may fire at the
  // same second — that's fine and expected (e.g. Reasoning Beat + Story
  // Integration overlap). We coalesce per-chord runs separately.
  const events = []; // {chord, start, end, intensity}
  for (const def of CHORDS) {
    let runStart = -1;
    let runIntensities = [];
    for (let s = 0; s < dur; s += 1) {
      const out = def.rule(secValues[s]);
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
  return events;
}

/** Build a short prose progression like "Visceral Hit → Reasoning Beat → ..." */
export function progressionString(events) {
  if (!events.length) return "Baseline throughout — no chord crossed threshold.";
  // Walk events in order; collapse adjacent identical chords.
  const seq = [];
  for (const e of events) {
    if (!seq.length || seq[seq.length - 1] !== e.chord) seq.push(e.chord);
  }
  // Cap at 6 entries with an ellipsis for readability.
  const trimmed = seq.length > 6 ? seq.slice(0, 6).concat(["…"]) : seq;
  return trimmed
    .map((k) => (k === "…" ? "…" : (CHORDS_BY_KEY[k] && CHORDS_BY_KEY[k].name) || k))
    .join("  →  ");
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

  // We need at least three of the seven roles to have any chord chance —
  // the simplest meaningful chord is two-system, so two roles is the floor.
  const presentRoles = new Set();
  for (const d of dimensions) {
    const r = roleOf(d);
    if (r) presentRoles.add(r);
  }
  if (presentRoles.size < 2) {
    root.hidden = true;
    return false;
  }

  const eventsA = classifyChords(dimensions, durationA || 30, "a");
  const eventsB = classifyChords(dimensions, durationB || 30, "b");

  const totalA = Math.max(durationA || 30, 1);
  const totalB = Math.max(durationB || 30, 1);
  const totalMax = Math.max(totalA, totalB);

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

    <div class="chord-progression-pair">
      ${renderSide(labelA, "a", eventsA, totalA, totalMax)}
      ${renderSide(labelB, "b", eventsB, totalB, totalMax)}
    </div>

    <details class="chord-details">
      <summary>The seven chords — formulas, science, citations ↓</summary>
      <div class="chord-defs-grid">
        ${CHORDS.map(renderChordCard).join("")}
      </div>
      <p class="chord-fineprint">
        Threshold values are v1 defaults derived from TRIBEv2 output distribution
        and cognitive-load chunking literature, pending ground-truth recalibration.
        See <a href="/research">/research</a> for the full methodology.
      </p>
    </details>
  `;

  // Hover tooltip — show the chord name and time on hover of any block.
  root.querySelectorAll(".chord-block").forEach((node) => {
    node.addEventListener("mouseenter", () => node.classList.add("is-hover"));
    node.addEventListener("mouseleave", () => node.classList.remove("is-hover"));
  });

  return true;
}

function renderSide(label, side, events, dur, totalMax) {
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
  const progression = progressionString(events);
  const summary = events.length
    ? `${events.length} chord event${events.length === 1 ? "" : "s"} across ${fmtSec(dur)}`
    : `No chords crossed threshold across ${fmtSec(dur)}`;
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
          <div class="chord-strip-blocks">${blocks || `<div class="chord-empty">No chords above threshold</div>`}</div>
        </div>
      </div>
      <p class="chord-progression-line">
        <strong>Progression:</strong> ${escapeHtml(progression)}
      </p>
    </div>
  `;
}

function axisTicks(dur) {
  // 5 evenly-spaced ticks, e.g. 0:00, 0:08, 0:15, 0:23, 0:30
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
