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

/** Orbit offsets from fit-to-bounds baseline (radians / scale), not absolute camera coords (3D-005). */
const DIMENSION_VIEWS = {
  personal_resonance: { yaw: 0, pitch: 0, distScale: 1 },
  social_thinking: { yaw: -0.38, pitch: 0.06, distScale: 1.05 },
  brain_effort: { yaw: 0.38, pitch: 0.1, distScale: 1.05 },
  language_depth: { yaw: 0.32, pitch: 0, distScale: 1.04 },
  gut_reaction: { yaw: 0.28, pitch: -0.1, distScale: 1.08 },
  memory_encoding: { yaw: 0.26, pitch: -0.14, distScale: 1.06 },
  attention_salience: { yaw: 0, pitch: 0.42, distScale: 1.1 },
};

const demoDisposers = [];
let brain3dModulePromise = null;

function drawFallbackSimpleBrain(canvas, label = "Brain preview fallback") {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width || 420;
  const h = canvas.height || 300;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#060708";
  ctx.fillRect(0, 0, w, h);
  const cx = w * 0.5;
  const cy = h * 0.5;
  const rx = w * 0.22;
  const ry = h * 0.34;
  const g = ctx.createLinearGradient(cx - rx * 1.3, cy, cx + rx * 1.3, cy);
  g.addColorStop(0, "rgba(80,120,220,0.82)");
  g.addColorStop(0.5, "rgba(194,198,205,0.66)");
  g.addColorStop(1, "rgba(92,210,184,0.85)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.ellipse(cx - w * 0.1, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(cx + w * 0.1, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "rgba(225,232,240,0.82)";
  ctx.font = "12px -apple-system, Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(label, cx, h - 16);
}

async function loadBrain3dModule() {
  if (!brain3dModulePromise) {
    brain3dModulePromise = import("./loadingBrain3d.js").catch((err) => {
      derror("loadingBrain3d module import failed", err?.stack || err);
      return null;
    });
  }
  return brain3dModulePromise;
}

/** Synthetic vertex patterns for marketing demo (same pipeline as app — not live API output). */
function buildDemoVertices(profile) {
  const out = new Float32Array(20484);
  for (let i = 0; i < 20484; i += 1) {
    const t = i / 20484;
    let v = 0.12 * Math.sin(t * 48 + (profile === "b" ? 1.2 : 0));
    if (i < 10242) v += profile === "b" ? 0.42 : 0.1;
    else v += profile === "b" ? 0.08 : 0.28;
    v += 0.04 * Math.sin(i * 0.08);
    out[i] = v;
  }
  return out;
}

async function mountDemoActivationBrains() {
  const canvasA = document.getElementById("demoBrainCanvasA");
  const canvasB = document.getElementById("demoBrainCanvasB");
  const canvasDiff = document.getElementById("demoDiffCanvas");
  if (!canvasA || !canvasB || !canvasDiff) {
    derror("mountDemoActivationBrains:missing canvas");
    return;
  }
  const mod = await loadBrain3dModule();
  if (!mod?.mountActivationBrainCanvas) {
    derror("mountDemoActivationBrains:no mountActivationBrainCanvas");
    return;
  }
  const va = buildDemoVertices("a");
  const vb = buildDemoVertices("b");
  const vDiff = new Float32Array(20484);
  for (let i = 0; i < 20484; i += 1) vDiff[i] = vb[i] - va[i];
  try {
    const dA = await mod.mountActivationBrainCanvas(canvasA, { values: va, mode: "activation" });
    const dB = await mod.mountActivationBrainCanvas(canvasB, { values: vb, mode: "activation" });
    const dD = await mod.mountActivationBrainCanvas(canvasDiff, { values: vDiff, mode: "diff" });
    demoDisposers.push(dA, dB, dD);
    dlog("mountDemoActivationBrains:ok");
  } catch (err) {
    derror("mountDemoActivationBrains:failed", err?.stack || err);
  }
}

async function fetchDimensionMasks() {
  const dm = await fetch("/api/dimension-masks");
  if (dm.ok) {
    const data = await dm.json();
    const masks = {};
    for (const [key, b64] of Object.entries(data)) {
      const bin = atob(b64);
      const u = new Uint8Array(20484);
      for (let i = 0; i < 20484; i += 1) u[i] = bin.charCodeAt(i) ? 1 : 0;
      masks[key] = u;
    }
    dlog("fetchDimensionMasks:api_dimension_masks", { keys: Object.keys(masks) });
    return masks;
  }
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
  dlog("fetchDimensionMasks:atlas_fallback_no_heuristic", { keys: Object.keys(masks) });
  return masks;
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
  const brain3d = await loadBrain3dModule();
  const heroCanvas = document.getElementById("landingHeroBrainCanvas");
  if (heroCanvas) {
    const r = heroCanvas.getBoundingClientRect();
    dlog("heroCanvas:found", {
      width: Math.round(r.width),
      height: Math.round(r.height),
      cssDisplay: getComputedStyle(heroCanvas).display,
    });
    try {
      if (brain3d?.mountLoadingBrainCanvas) {
        demoDisposers.push(
          brain3d.mountLoadingBrainCanvas(heroCanvas, {
            motionSpeed: 0.22,
            fitMargin: 1.16,
            baseYaw: -0.42,
            basePitch: -0.08,
            driftYaw: 0.045,
            driftPitch: 0.02,
            color: 0x67d1c5,
            emissive: 0x0b2320,
            emissiveIntensity: 0.18,
            metalness: 0.05,
            roughness: 0.68,
          }),
        );
        dlog("heroCanvas:mount requested");
      } else {
        derror("heroCanvas:3d module unavailable; drawing 2d fallback");
        drawFallbackSimpleBrain(heroCanvas, "3D unavailable - fallback preview");
      }
    } catch (err) {
      derror("heroCanvas:mount failed", err?.stack || err);
      drawFallbackSimpleBrain(heroCanvas, "Render failed - fallback preview");
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
  await mountDemoActivationBrains();

  let controller = null;
  try {
    if (brain3d?.mountHighlightBrainCanvas) {
      controller = await brain3d.mountHighlightBrainCanvas(explainerCanvas, {
        initialMask: masks.personal_resonance,
        initialView: DIMENSION_VIEWS.personal_resonance,
      });
      demoDisposers.push(() => controller.dispose());
      dlog("explainerCanvas:mountHighlight ok");
    } else {
      derror("explainerCanvas:3d module unavailable; drawing 2d fallback");
      drawFallbackSimpleBrain(explainerCanvas, "Explainer fallback brain");
    }
  } catch (err) {
    derror("explainerCanvas:mountHighlight failed", err?.stack || err);
    drawFallbackSimpleBrain(explainerCanvas, "Explainer render failed");
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
    const view = DIMENSION_VIEWS[d.key] || DIMENSION_VIEWS.personal_resonance;
    if (controller && typeof controller.setDimension === "function") {
      controller.setDimension(masks[d.key], view);
      dlog("explainerCanvas:setDimension", d.key);
    }
  };

  dots.forEach((dot) => {
    dot.addEventListener("click", () => render(Number(dot.dataset.idx || 0)));
  });
  render(0);
}

wireSmoothAnchors();
initRevealOnScroll();
animateEvidenceChips();
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
