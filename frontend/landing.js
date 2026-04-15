import { buildHumanDelta } from "./delta_human.js";
import {
  mountLoadingBrainCanvas,
  mountHighlightBrainCanvas,
} from "./loadingBrain3d.js";

const LANDING_LOG_PREFIX = "[landing-debug]";
function dlog(...args) {
  window.__brainDiffDebugLogs = window.__brainDiffDebugLogs || [];
  window.__brainDiffDebugLogs.push({ ts: Date.now(), args });
  console.log(LANDING_LOG_PREFIX, ...args);
}

function derror(...args) {
  window.__brainDiffDebugLogs = window.__brainDiffDebugLogs || [];
  window.__brainDiffDebugLogs.push({ ts: Date.now(), error: true, args });
  console.error(LANDING_LOG_PREFIX, ...args);
}

window.addEventListener("error", (evt) => {
  derror("window.error", {
    message: evt.message,
    file: evt.filename,
    line: evt.lineno,
    col: evt.colno,
    error: evt.error?.stack || String(evt.error || ""),
  });
});

window.addEventListener("unhandledrejection", (evt) => {
  derror("window.unhandledrejection", evt.reason?.stack || String(evt.reason || evt));
});

const DEMO_DIMENSIONS = [
  {
    key: "personal_resonance",
    label: "Personal Resonance",
    meaning: "feels more personally relevant",
    magnitude: 0.38,
    direction: "B_higher",
    score_a: 0.17,
    score_b: 0.55,
    human: "3x stronger for Version B",
  },
  {
    key: "brain_effort",
    label: "Brain Effort",
    meaning: "demands more thinking effort",
    magnitude: 0.22,
    direction: "A_higher",
    score_a: 0.47,
    score_b: 0.25,
    human: "Version A demands noticeably more",
  },
  {
    key: "gut_reaction",
    label: "Gut Reaction",
    meaning: "lands more viscerally",
    magnitude: 0.15,
    direction: "B_higher",
    score_a: 0.18,
    score_b: 0.33,
    human: "Moderately stronger for Version B",
  },
  {
    key: "memory_encoding",
    label: "Memory Encoding",
    meaning: "is more likely to be remembered",
    magnitude: 0.11,
    direction: "B_higher",
    score_a: 0.2,
    score_b: 0.31,
    human: "Moderately stronger for Version B",
  },
  {
    key: "attention_salience",
    label: "Attention",
    meaning: "captures attentional resources",
    magnitude: 0.09,
    direction: "B_higher",
    score_a: 0.19,
    score_b: 0.28,
    human: "Slightly stronger for Version B",
  },
  {
    key: "language_depth",
    label: "Language Depth",
    meaning: "engages deeper meaning-making",
    magnitude: 0.09,
    direction: "A_higher",
    score_a: 0.34,
    score_b: 0.25,
    human: "Slightly stronger for Version A",
  },
  {
    key: "social_thinking",
    label: "Social Thinking",
    meaning: "pulls more social reasoning",
    magnitude: 0.04,
    direction: "neutral",
    score_a: 0.21,
    score_b: 0.25,
    human: "No meaningful difference",
  },
];

const ANNOTATED_DIMENSIONS = [
  {
    key: "personal_resonance",
    name: "Personal Resonance",
    region: "Medial prefrontal cortex",
    question: "\"Does this feel like it's about me?\"",
    description:
      "Tracks self-relevance processing. The same region predicted real-world anti-smoking campaign behavior better than self-report.",
    citation: "Falk et al., 2012",
  },
  {
    key: "social_thinking",
    name: "Social Thinking",
    region: "Temporoparietal junction",
    question: "\"Am I reasoning about other minds?\"",
    description:
      "Measures perspective-taking and social inference. Stronger response means the message pulls social cognition online.",
    citation: "Saxe & Kanwisher, 2003",
  },
  {
    key: "brain_effort",
    name: "Brain Effort",
    region: "Dorsolateral prefrontal cortex",
    question: "\"How hard is the brain working?\"",
    description:
      "Indexes cognitive load and control demand. Higher can reflect complexity, confusion, or active learning depending on context.",
    citation: "Owen et al., 2005",
  },
  {
    key: "language_depth",
    name: "Language Depth",
    region: "Broca's + Wernicke's network",
    question: "\"How deeply is meaning being extracted?\"",
    description:
      "Captures semantic parsing depth and structural language processing across canonical cortical language systems.",
    citation: "Fedorenko et al., 2010",
  },
  {
    key: "gut_reaction",
    name: "Gut Reaction",
    region: "Anterior insula",
    question: "\"Does this hit viscerally?\"",
    description:
      "Sensitive to felt salience, interoceptive intensity, and emotionally charged signals that create a bodily response.",
    citation: "Craig, 2009",
  },
  {
    key: "memory_encoding",
    name: "Memory Encoding",
    region: "Left ventrolateral prefrontal cortex",
    question: "\"Will this be remembered?\"",
    description:
      "The cortical driver of long-term memory formation. Higher activation here = higher likelihood of being stored. Neuro-Insight found this signal correlates 86% with real-world sales.",
    citation: "Paller & Wagner, 2002",
  },
  {
    key: "attention_salience",
    name: "Attention",
    region: "Dorsal attention network",
    question: "\"Is the brain orienting toward this?\"",
    description:
      "Controls where the brain directs its processing resources. Content that commands focus through urgency, novelty, or salience lights up this network.",
    citation: "Corbetta & Shulman, 2002",
  },
];

const DIMENSION_CAMERAS = {
  personal_resonance: {
    position: { x: 50, y: 10, z: 0 },
    target: { x: 0, y: 0, z: 0 },
  },
  social_thinking: {
    position: { x: -200, y: 20, z: 40 },
    target: { x: 0, y: 0, z: 0 },
  },
  brain_effort: {
    position: { x: 200, y: 40, z: 40 },
    target: { x: 0, y: 0, z: 0 },
  },
  language_depth: {
    position: { x: 200, y: 0, z: 20 },
    target: { x: 0, y: -10, z: 0 },
  },
  gut_reaction: {
    position: { x: 180, y: -10, z: 80 },
    target: { x: 0, y: -5, z: 0 },
  },
  memory_encoding: {
    position: { x: 180, y: -30, z: 60 },
    target: { x: 0, y: -10, z: 0 },
  },
  attention_salience: {
    position: { x: 0, y: 200, z: -40 },
    target: { x: 0, y: 0, z: 0 },
  },
};

const demoDisposers = [];

function renderDemoBars() {
  const container = document.getElementById("landingDemoBars");
  if (!container) {
    derror("renderDemoBars:missing container #landingDemoBars");
    return;
  }
  dlog("renderDemoBars:start", { rows: DEMO_DIMENSIONS.length });
  container.innerHTML = "";
  const maxAbs = Math.max(0.001, ...DEMO_DIMENSIONS.map((row) => row.magnitude));

  DEMO_DIMENSIONS.forEach((row, idx) => {
    const width = Math.max(8, Math.round((Math.abs(row.magnitude) / maxAbs) * 100));
    const rowEl = document.createElement("div");
    rowEl.className = "bar-row demo-bar-row";
    rowEl.innerHTML = `
      <div class="bar-copy">
        <span class="bar-label">${row.label}</span>
        <span class="bar-meaning">${row.meaning}</span>
      </div>
      <div class="bar-track">
        <div class="bar-fill ${row.direction === "A_higher" ? "left" : "right"}" style="width:0%" data-target-width="${width}%"></div>
      </div>
      <div class="bar-meta">
        <span class="delta">${row.human || buildHumanDelta(row)}</span>
      </div>
    `;
    container.appendChild(rowEl);
    rowEl.style.setProperty("--bar-delay", `${idx * 80}ms`);
  });

  requestAnimationFrame(() => {
    container.querySelectorAll(".bar-fill[data-target-width]").forEach((fill) => {
      fill.style.width = fill.getAttribute("data-target-width");
    });
  });
}

async function fetchDimensionMasks() {
  const res = await fetch("/api/vertex-atlas");
  if (!res.ok) throw new Error(`vertex-atlas ${res.status}`);
  const atlas = await res.json();
  const labels = atlas.labels || [];
  const dimensionsByLabel = atlas.dimensions || {};
  const masks = Object.fromEntries(ANNOTATED_DIMENSIONS.map((d) => [d.key, new Uint8Array(20484)]));
  for (let i = 0; i < Math.min(labels.length, 20484); i += 1) {
    const dims = dimensionsByLabel[labels[i]] || [];
    dims.forEach((dimKey) => {
      if (masks[dimKey]) masks[dimKey][i] = 1;
    });
  }
  // Temporary fallback for dimensions that do not resolve from atlas labels on the frontend.
  // TODO: replace with backend-served precomputed boolean masks per dimension.
  const fallbackRanges = {
    attention_salience: [
      [1200, 1700],
      [3400, 3950],
      [11242, 11742],
      [13450, 14000],
    ],
    memory_encoding: [
      [220, 520],
      [980, 1280],
    ],
  };
  Object.entries(fallbackRanges).forEach(([key, ranges]) => {
    const m = masks[key];
    if (!m) return;
    const count = Array.from(m).filter(Boolean).length;
    if (count > 0) return;
    ranges.forEach(([start, end]) => {
      const s = Math.max(0, start);
      const e = Math.min(20484, end);
      for (let i = s; i < e; i += 1) m[i] = 1;
    });
    dlog("fetchDimensionMasks:fallback_applied", {
      key,
      count: Array.from(m).filter(Boolean).length,
    });
  });
  return masks;
}

function drawDemoBrainPlaceholder(canvas, emphasis = "a") {
  if (!canvas) {
    derror("drawDemoBrainPlaceholder:missing canvas", { emphasis });
    return;
  }
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#060708";
  ctx.fillRect(0, 0, w, h);

  const cx = w * 0.5;
  const cy = h * 0.5;
  const rx = w * 0.26;
  const ry = h * 0.34;
  const drawHemisphere = (xShift, hotBias) => {
    const grad = ctx.createRadialGradient(cx + xShift * 0.35, cy - 10, 8, cx + xShift, cy, rx * 1.2);
    grad.addColorStop(0, hotBias ? "rgba(245,120,96,0.85)" : "rgba(90,200,184,0.78)");
    grad.addColorStop(1, "rgba(48,62,84,0.72)");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.ellipse(cx + xShift, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.22)";
    ctx.lineWidth = 1;
    for (let i = -5; i <= 5; i += 1) {
      ctx.beginPath();
      ctx.ellipse(cx + xShift + i * 4, cy + Math.sin(i) * 5, rx * 0.75, ry * 0.82, i * 0.04, 0, Math.PI * 2);
      ctx.stroke();
    }
  };
  drawHemisphere(-w * 0.12, emphasis === "b");
  drawHemisphere(w * 0.12, emphasis === "a");
}

function drawDemoDiffPlaceholder(canvas) {
  if (!canvas) {
    derror("drawDemoDiffPlaceholder:missing canvas");
    return;
  }
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#060708";
  ctx.fillRect(0, 0, w, h);
  const cx = w * 0.5;
  const cy = h * 0.5;
  const rx = w * 0.2;
  const ry = h * 0.33;
  const drawHalf = (xShift) => {
    ctx.save();
    ctx.beginPath();
    ctx.ellipse(cx + xShift, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.clip();
    const g = ctx.createLinearGradient(cx + xShift - rx, cy, cx + xShift + rx, cy);
    g.addColorStop(0, "rgba(60,100,220,0.95)");
    g.addColorStop(0.5, "rgba(220,220,220,0.84)");
    g.addColorStop(1, "rgba(236,108,88,0.95)");
    ctx.fillStyle = g;
    ctx.fillRect(cx + xShift - rx, cy - ry, rx * 2, ry * 2);
    ctx.restore();
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.24)";
    ctx.lineWidth = 1;
    for (let i = -4; i <= 4; i += 1) {
      ctx.beginPath();
      ctx.ellipse(cx + xShift + i * 3, cy + Math.cos(i) * 5, rx * 0.78, ry * 0.8, i * 0.05, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  };
  drawHalf(-w * 0.1);
  drawHalf(w * 0.1);
}

function mountDemoBrainVisuals() {
  const canvasA = document.getElementById("demoBrainCanvasA");
  const canvasB = document.getElementById("demoBrainCanvasB");
  const canvasDiff = document.getElementById("demoDiffCanvas");
  if (!canvasA || !canvasB || !canvasDiff) {
    derror("mountDemoBrainVisuals:missing canvas", {
      hasA: Boolean(canvasA),
      hasB: Boolean(canvasB),
      hasDiff: Boolean(canvasDiff),
    });
    return;
  }
  dlog("mountDemoBrainVisuals:start", {
    a: { w: canvasA.width, h: canvasA.height },
    b: { w: canvasB.width, h: canvasB.height },
    diff: { w: canvasDiff.width, h: canvasDiff.height },
  });
  const repaint = () => {
    drawDemoBrainPlaceholder(canvasA, "a");
    drawDemoBrainPlaceholder(canvasB, "b");
    drawDemoDiffPlaceholder(canvasDiff);
  };
  repaint();
  window.addEventListener("resize", repaint, { passive: true });
  demoDisposers.push(() => window.removeEventListener("resize", repaint));
}

function wireSmoothAnchors() {
  dlog("wireSmoothAnchors:start");
  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      const target = link.getAttribute("href");
      if (!target || target === "#") return;
      const element = document.querySelector(target);
      if (!element) return;
      event.preventDefault();
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function initRevealOnScroll() {
  dlog("initRevealOnScroll:start");
  const targets = document.querySelectorAll(".landing-main section, .method-step, .demo-text-card");
  targets.forEach((node) => node.classList.add("reveal-init"));
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("reveal-in");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.12, rootMargin: "0px 0px -40px 0px" },
  );
  targets.forEach((node) => observer.observe(node));
}

function animateEvidenceChips() {
  dlog("animateEvidenceChips:start");
  const chips = document.querySelectorAll(".evidence-chip");
  chips.forEach((chip, idx) => {
    chip.style.setProperty("--chip-delay", `${idx * 120}ms`);
    chip.classList.add("chip-enter");
  });
}

function initHeroParticles() {
  const canvas = document.getElementById("landingHeroCanvas");
  if (!canvas) {
    derror("initHeroParticles:missing #landingHeroCanvas");
    return;
  }
  dlog("initHeroParticles:start");
  const ctx = canvas.getContext("2d");
  const DPR = Math.max(1, Math.min(window.devicePixelRatio || 1, 2));
  let particles = [];
  let raf = null;

  function resize() {
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * DPR;
    canvas.height = rect.height * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    const count = Math.max(32, Math.min(88, Math.floor(rect.width / 14)));
    particles = Array.from({ length: count }, () => ({
      x: Math.random() * rect.width,
      y: Math.random() * rect.height,
      r: Math.random() * 2.2 + 0.7,
      vx: (Math.random() - 0.5) * 0.12,
      vy: (Math.random() - 0.5) * 0.12,
      a: Math.random() * Math.PI * 2,
    }));
  }

  function draw(t) {
    const rect = canvas.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    ctx.clearRect(0, 0, width, height);
    particles.forEach((p, i) => {
      p.x += p.vx + Math.sin(t / 1300 + p.a) * 0.02;
      p.y += p.vy + Math.cos(t / 1700 + p.a) * 0.02;
      if (p.x < -20) p.x = width + 20;
      if (p.x > width + 20) p.x = -20;
      if (p.y < -20) p.y = height + 20;
      if (p.y > height + 20) p.y = -20;
      for (let j = i + 1; j < particles.length; j += 1) {
        const q = particles[j];
        const dx = p.x - q.x;
        const dy = p.y - q.y;
        const dist = Math.hypot(dx, dy);
        if (dist < 90) {
          const alpha = 0.06 * (1 - dist / 90);
          ctx.strokeStyle = `rgba(255,255,255,${alpha})`;
          ctx.lineWidth = 0.7;
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(q.x, q.y);
          ctx.stroke();
        }
      }
      const alpha = 0.22 + 0.22 * Math.sin(t / 1800 + p.a);
      ctx.fillStyle = `rgba(130,220,210,${alpha})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    });
    raf = requestAnimationFrame(draw);
  }

  resize();
  raf = requestAnimationFrame(draw);
  window.addEventListener("resize", resize, { passive: true });
  window.addEventListener("beforeunload", () => cancelAnimationFrame(raf), { once: true });
}

async function initLandingBrainsAndExplainer() {
  dlog("initLandingBrainsAndExplainer:start");
  const heroCanvas = document.getElementById("landingHeroBrainCanvas");
  if (heroCanvas) {
    const r = heroCanvas.getBoundingClientRect();
    dlog("heroCanvas:found", {
      width: Math.round(r.width),
      height: Math.round(r.height),
      cssDisplay: getComputedStyle(heroCanvas).display,
    });
    try {
      demoDisposers.push(
        mountLoadingBrainCanvas(heroCanvas, {
          height: 420,
          rotationSpeed: 0.28,
        }),
      );
      dlog("heroCanvas:mount requested");
    } catch (err) {
      derror("heroCanvas:mount failed", err?.stack || err);
    }
  } else {
    derror("initLandingBrainsAndExplainer:missing #landingHeroBrainCanvas");
  }

  const explainerCanvas = document.getElementById("landingBrainCanvas");
  const titleEl = document.getElementById("explainerAnnotationTitle");
  const regionEl = document.getElementById("explainerAnnotationRegion");
  const bodyEl = document.getElementById("explainerAnnotationBody");
  const citeEl = document.getElementById("explainerAnnotationCite");
  const dotsEl = document.getElementById("explainerDimensionDots");
  if (!explainerCanvas || !titleEl || !regionEl || !bodyEl || !citeEl || !dotsEl) {
    derror("initLandingBrainsAndExplainer:missing explainer nodes", {
      explainerCanvas: Boolean(explainerCanvas),
      titleEl: Boolean(titleEl),
      regionEl: Boolean(regionEl),
      bodyEl: Boolean(bodyEl),
      citeEl: Boolean(citeEl),
      dotsEl: Boolean(dotsEl),
    });
    return;
  }
  const er = explainerCanvas.getBoundingClientRect();
  dlog("explainerCanvas:found", {
    width: Math.round(er.width),
    height: Math.round(er.height),
    cssDisplay: getComputedStyle(explainerCanvas).display,
  });

  const masks = await fetchDimensionMasks();
  dlog("fetchDimensionMasks:ok", {
    keys: Object.keys(masks),
    prCount: masks.personal_resonance ? Array.from(masks.personal_resonance).filter(Boolean).length : -1,
    asCount: masks.attention_salience ? Array.from(masks.attention_salience).filter(Boolean).length : -1,
  });
  mountDemoBrainVisuals();

  let controller = null;
  try {
    controller = await mountHighlightBrainCanvas(explainerCanvas, {
      initialMask: masks.personal_resonance,
      height: 300,
      initialCamera: DIMENSION_CAMERAS.personal_resonance.position,
      initialTarget: DIMENSION_CAMERAS.personal_resonance.target,
    });
    demoDisposers.push(() => controller.dispose());
    dlog("explainerCanvas:mountHighlight ok");
  } catch (err) {
    derror("explainerCanvas:mountHighlight failed", err?.stack || err);
  }

  let idx = 0;
  dotsEl.innerHTML = ANNOTATED_DIMENSIONS.map((_, i) => `<button type="button" class="explainer-dot" data-idx="${i}" aria-label="Show dimension ${i + 1}"></button>`).join("");
  const dots = [...dotsEl.querySelectorAll(".explainer-dot")];

  const render = (nextIdx) => {
    idx = nextIdx % ANNOTATED_DIMENSIONS.length;
    const d = ANNOTATED_DIMENSIONS[idx];
    titleEl.textContent = d.name;
    regionEl.textContent = `${d.region} · ${d.question}`;
    bodyEl.textContent = d.description;
    citeEl.textContent = d.citation;
    dots.forEach((dot, i) => dot.classList.toggle("active", i === idx));
    const cam = DIMENSION_CAMERAS[d.key] || DIMENSION_CAMERAS.personal_resonance;
    if (controller && typeof controller.setDimension === "function") {
      controller.setDimension(masks[d.key], cam.position, cam.target);
      dlog("explainerCanvas:setDimension", d.key);
    }
  };

  dots.forEach((dot) => {
    dot.addEventListener("click", () => render(Number(dot.dataset.idx || 0)));
  });
  render(0);
  const interval = setInterval(() => render(idx + 1), 4400);
  demoDisposers.push(() => clearInterval(interval));
}

renderDemoBars();
wireSmoothAnchors();
initRevealOnScroll();
animateEvidenceChips();
initHeroParticles();
initLandingBrainsAndExplainer().catch((err) => {
  derror("Landing brain init failed:", err?.stack || err);
});

setTimeout(() => {
  const heroCanvas = document.getElementById("landingHeroBrainCanvas");
  const explainerCanvas = document.getElementById("landingBrainCanvas");
  dlog("postInit:canvas-state", {
    hero: heroCanvas
      ? {
          width: heroCanvas.width,
          height: heroCanvas.height,
          clientWidth: heroCanvas.clientWidth,
          clientHeight: heroCanvas.clientHeight,
        }
      : null,
    explainer: explainerCanvas
      ? {
          width: explainerCanvas.width,
          height: explainerCanvas.height,
          clientWidth: explainerCanvas.clientWidth,
          clientHeight: explainerCanvas.clientHeight,
        }
      : null,
    totalLogs: (window.__brainDiffDebugLogs || []).length,
  });
}, 2500);

window.addEventListener("beforeunload", () => {
  demoDisposers.forEach((dispose) => {
    if (typeof dispose === "function") dispose();
  });
});
