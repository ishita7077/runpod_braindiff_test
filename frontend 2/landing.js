const DIMENSIONS = [
  {
    key: "personal_resonance",
    name: "Personal relevance",
    region: "Medial prefrontal cortex · Does this feel like it is about me?",
    body:
      "Tracks self-relevance processing. Stronger response here matters when two versions are informationally similar but personally unequal.",
    cite: "Falk et al., 2012",
  },
  {
    key: "social_thinking",
    name: "Social reasoning",
    region: "Temporoparietal junction · Am I modeling another mind?",
    body:
      "Highlights systems involved in perspective-taking and social inference when a message pulls more on people, motives, or intention.",
    cite: "Saxe & Kanwisher, 2003",
  },
  {
    key: "brain_effort",
    name: "Processing effort",
    region: "Dorsolateral prefrontal cortex · How hard is the system working?",
    body:
      "Indexes control demand and cognitive load. Higher is not always worse, but it usually means the message asks more of the viewer.",
    cite: "Owen et al., 2005",
  },
  {
    key: "language_depth",
    name: "Language depth",
    region: "Broca's + Wernicke's network · How deeply is meaning being parsed?",
    body:
      "Captures structural and semantic language processing across canonical cortical language systems.",
    cite: "Fedorenko et al., 2010",
  },
  {
    key: "gut_reaction",
    name: "Gut reaction",
    region: "Anterior insula · Does this hit viscerally?",
    body:
      "Sensitive to felt salience and interoceptive intensity — the bodily edge of a message, not just its literal content.",
    cite: "Craig, 2009",
  },
  {
    key: "memory_encoding",
    name: "Memory encoding",
    region: "Left ventrolateral prefrontal cortex · Will this stick?",
    body:
      "Marks a cortical driver of memory formation. Useful when two versions feel similar in the moment but differ in what tends to endure.",
    cite: "Paller & Wagner, 2002",
  },
  {
    key: "attention_salience",
    name: "Attention",
    region: "Dorsal attention network · Is the system orienting toward this?",
    body:
      "Reflects orienting and selection. Content that commands focus through novelty, urgency, or contrast tends to pull here.",
    cite: "Corbetta & Shulman, 2002",
  },
];

const DIMENSION_VIEWS = {
  personal_resonance: { yaw: 0, pitch: 0, distScale: 1 },
  social_thinking: { yaw: -0.36, pitch: 0.05, distScale: 1.05 },
  brain_effort: { yaw: 0.38, pitch: 0.08, distScale: 1.04 },
  language_depth: { yaw: 0.28, pitch: 0.02, distScale: 1.04 },
  gut_reaction: { yaw: 0.22, pitch: -0.12, distScale: 1.08 },
  memory_encoding: { yaw: 0.24, pitch: -0.15, distScale: 1.07 },
  attention_salience: { yaw: 0, pitch: 0.4, distScale: 1.1 },
};

const disposers = [];
let brainModulePromise = null;

function loadBrainModule() {
  if (!brainModulePromise) {
    brainModulePromise = import("./loadingBrain3d.js").catch((error) => {
      console.error("[landing] loadingBrain3d import failed", error);
      return null;
    });
  }
  return brainModulePromise;
}

function buildIllustrativeVertices(profile) {
  const out = new Float32Array(20484);
  for (let i = 0; i < out.length; i += 1) {
    const hemi = i < 10242 ? 0 : 1;
    const local = hemi === 0 ? i : i - 10242;
    const t = local / 10242;
    const waveA = 0.07 * Math.sin(t * 44 + (profile === "b" ? 1.1 : 0.1));
    const waveB = 0.04 * Math.cos(t * 19 + (hemi === 0 ? 0.9 : 2.2));
    const ridge = Math.exp(-Math.pow(t - 0.54, 2) / (profile === "b" ? 0.012 : 0.022));
    const pocket = Math.exp(-Math.pow(t - (hemi === 0 ? 0.32 : 0.67), 2) / 0.008);
    const bias = profile === "b"
      ? hemi === 0
        ? 0.2 + ridge * 0.24 + pocket * 0.06
        : 0.18 + ridge * 0.31
      : hemi === 0
        ? 0.12 + ridge * 0.1
        : 0.15 + ridge * 0.16 + pocket * 0.05;
    out[i] = waveA + waveB + bias;
  }
  return out;
}

async function mountHeroBrain() {
  const canvas = document.getElementById("landingHeroBrainCanvas");
  if (!canvas) return;
  const mod = await loadBrainModule();
  if (!mod?.mountLoadingBrainCanvas) return;
  const dispose = await mod.mountLoadingBrainCanvas(canvas, {
    motionSpeed: 0.18,
    fitMargin: 1.14,
    baseYaw: -0.48,
    basePitch: -0.05,
    driftYaw: 0.04,
    driftPitch: 0.018,
    color: 0xd3d9e1,
    emissive: 0x12161c,
    emissiveIntensity: 0.24,
    metalness: 0.1,
    roughness: 0.62,
    clearcoat: 0.24,
    clearcoatRoughness: 0.58,
    reflectivity: 0.46,
    sheen: 0.24,
    sheenColor: 0xf2dfbc,
    sheenRoughness: 0.64,
  });
  disposers.push(dispose);
}

async function mountLiveComparison() {
  const canvas = document.getElementById("liveDiffCanvas");
  if (!canvas) return;
  const mod = await loadBrainModule();
  if (!mod?.mountActivationBrainCanvas) return;
  const a = buildIllustrativeVertices("a");
  const b = buildIllustrativeVertices("b");
  const diff = new Float32Array(a.length);
  for (let i = 0; i < diff.length; i += 1) diff[i] = b[i] - a[i];
  const dispose = await mod.mountActivationBrainCanvas(canvas, {
    values: diff,
    mode: "diff",
    rotationSpeed: 0.12,
    palette: "steel-gold",
  });
  disposers.push(dispose);
}

async function fetchDimensionMasks() {
  const response = await fetch("/api/dimension-masks");
  if (!response.ok) throw new Error(`dimension-masks ${response.status}`);
  const data = await response.json();
  const masks = {};
  Object.entries(data).forEach(([key, b64]) => {
    const bin = atob(b64);
    const mask = new Uint8Array(20484);
    for (let i = 0; i < 20484; i += 1) mask[i] = bin.charCodeAt(i) ? 1 : 0;
    masks[key] = mask;
  });
  return masks;
}

async function mountLensBrain() {
  const canvas = document.getElementById("bdLensCanvas");
  const dotsEl = document.getElementById("lensDimensionDots");
  const titleEl = document.getElementById("lensAnnotationTitle");
  const regionEl = document.getElementById("lensAnnotationRegion");
  const bodyEl = document.getElementById("lensAnnotationBody");
  const citeEl = document.getElementById("lensAnnotationCite");
  if (!canvas || !dotsEl || !titleEl || !regionEl || !bodyEl || !citeEl) return;

  const mod = await loadBrainModule();
  if (!mod?.mountHighlightBrainCanvas) return;
  const masks = await fetchDimensionMasks();
  const controller = await mod.mountHighlightBrainCanvas(canvas, {
    initialMask: masks.personal_resonance,
    initialView: DIMENSION_VIEWS.personal_resonance,
  });
  disposers.push(() => controller.dispose());

  dotsEl.innerHTML = DIMENSIONS.map((dimension, index) => (
    `<button type="button" class="bd-dimension-pill${index === 0 ? " active" : ""}" data-key="${dimension.key}">${dimension.name}</button>`
  )).join("");

  function renderDimension(key) {
    const item = DIMENSIONS.find((dimension) => dimension.key === key) || DIMENSIONS[0];
    titleEl.textContent = item.name;
    regionEl.textContent = item.region;
    bodyEl.textContent = item.body;
    citeEl.textContent = item.cite;
    dotsEl.querySelectorAll(".bd-dimension-pill").forEach((pill) => {
      pill.classList.toggle("active", pill.dataset.key === item.key);
    });
    controller.setDimension(masks[item.key], DIMENSION_VIEWS[item.key] || DIMENSION_VIEWS.personal_resonance);
  }

  dotsEl.addEventListener("click", (event) => {
    const button = event.target.closest(".bd-dimension-pill");
    if (!button) return;
    renderDimension(button.dataset.key);
  });
}

function initRevealOnScroll() {
  const nodes = [...document.querySelectorAll(".reveal-on-scroll")];
  if (!nodes.length) return;
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.14, rootMargin: "0px 0px -40px 0px" },
  );
  nodes.forEach((node) => observer.observe(node));
}

function wireSmoothAnchors() {
  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      const href = link.getAttribute("href");
      if (!href || href === "#") return;
      const target = document.querySelector(href);
      if (!target) return;
      event.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function wireDemoButtons() {
  document.querySelectorAll(".bd-play-button").forEach((button) => {
    button.addEventListener("click", () => {
      window.location.href = "./app.html";
    });
  });
}

async function init() {
  wireSmoothAnchors();
  initRevealOnScroll();
  wireDemoButtons();
  await Promise.allSettled([mountHeroBrain(), mountLiveComparison(), mountLensBrain()]);
}

init().catch((error) => {
  console.error("[landing] init failed", error);
});

window.addEventListener("beforeunload", () => {
  disposers.forEach((dispose) => {
    if (typeof dispose === "function") dispose();
  });
});
