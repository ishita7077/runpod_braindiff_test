/**
 * Shared fsaverage5 brain renderer for loading, landing hero, explainer, and demo visuals.
 */
import * as THREE from "three";
import {
  applyOrbitFromFitPosition,
  applyPerspectiveBrainFit,
  getBrainWorldCenter,
  normalizeBrainGroup,
  pickWebGLPowerPreference,
  syncRendererToViewport,
} from "./brainViewport.js";

const VIEW_BLEND_MS = 780;

function easeOutQuad(t) {
  const x = Math.min(1, Math.max(0, t));
  return x * (2 - x);
}

let _meshPayload = null;
const LOG_PREFIX = "[brain-render]";

function pushClientDebug(entry) {
  try {
    window.__brainDiffDebugLogs = window.__brainDiffDebugLogs || [];
    window.__brainDiffDebugLogs.push({ ts: Date.now(), ...entry });
  } catch {
    /* no-op */
  }
}

function log(...args) {
  pushClientDebug({ source: "brain-render", level: "log", args });
  console.log(LOG_PREFIX, ...args);
}

function warn(...args) {
  pushClientDebug({ source: "brain-render", level: "warn", args });
  console.warn(LOG_PREFIX, ...args);
}

function error(...args) {
  pushClientDebug({ source: "brain-render", level: "error", args });
  console.error(LOG_PREFIX, ...args);
}

function _flatCoord(coord) {
  if (!coord?.length) return new Float32Array(0);
  if (typeof coord[0] === "number") return Float32Array.from(coord);
  return Float32Array.from(coord.flatMap((p) => p));
}

function _flatFaces(faces) {
  if (!faces?.length) return [];
  if (typeof faces[0] === "number") return faces;
  return faces.flatMap((f) => f);
}

function _geometry(coord, faces) {
  const flatPos = _flatCoord(coord);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(flatPos, 3));
  g.setIndex(_flatFaces(faces));
  g.computeVertexNormals();
  return g;
}

function _disposeScene(scene, renderer) {
  renderer.dispose();
  scene.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose();
    const m = obj.material;
    if (m) {
      if (Array.isArray(m)) m.forEach((x) => x.dispose());
      else m.dispose();
    }
  });
}

function _bwr(t) {
  const x = Math.max(-1, Math.min(1, t));
  if (x <= 0) {
    const u = x + 1;
    return [u, u, 1];
  }
  const u = x;
  return [1, 1 - u, 1 - u];
}

export async function fetchFsaverageMesh() {
  if (_meshPayload) return _meshPayload;
  log("fetchFsaverageMesh:start");
  const res = await fetch("/api/brain-mesh");
  if (!res.ok) throw new Error(`brain-mesh ${res.status}`);
  _meshPayload = await res.json();
  log("fetchFsaverageMesh:ok", {
    hasLH: Boolean(_meshPayload?.lh_coord),
    hasRH: Boolean(_meshPayload?.rh_coord),
    lhVerts: Array.isArray(_meshPayload?.lh_coord) ? _meshPayload.lh_coord.length : -1,
    rhVerts: Array.isArray(_meshPayload?.rh_coord) ? _meshPayload.rh_coord.length : -1,
  });
  return _meshPayload;
}

/** Hemispheres use mesh vertex positions only — no fixed lateral offset (3D-001). */
function _buildHemispheres(root, mesh, materialL, materialR) {
  const gL = _geometry(mesh.lh_coord, mesh.lh_faces);
  const gR = _geometry(mesh.rh_coord, mesh.rh_faces);
  const mL = new THREE.Mesh(gL, materialL);
  const mR = new THREE.Mesh(gR, materialR);
  mL.position.set(0, 0, 0);
  mR.position.set(0, 0, 0);
  root.add(mL, mR);
  return { gL, gR, mL, mR };
}

function resolveViewport(canvas) {
  return (
    canvas.closest(".loading-brain-frame, .hero-brain-canvas-wrapper, .landing-brain-view, .brain-viewport")
    || canvas.parentElement
  );
}

function _baseScene(canvas, { cameraFov = 38, near = 1, far = 520, alpha = true } = {}) {
  const rect = canvas.getBoundingClientRect();
  log("_baseScene:init", {
    canvasId: canvas.id || "(no-id)",
    width: Math.round(rect.width),
    height: Math.round(rect.height),
    dpr: window.devicePixelRatio || 1,
  });
  const scene = new THREE.Scene();
  scene.background = null;
  const camera = new THREE.PerspectiveCamera(cameraFov, 1, near, far);
  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha,
    powerPreference: pickWebGLPowerPreference(),
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const root = new THREE.Group();
  scene.add(root);

  scene.add(new THREE.AmbientLight(0xc8e8f0, 0.32));
  const key = new THREE.DirectionalLight(0xffffff, 1.05);
  key.position.set(50, 90, 70);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xa8d4e8, 0.45);
  fill.position.set(-40, 20, 60);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0x66e8d8, 0.42);
  rim.position.set(-60, -20, -80);
  scene.add(rim);
  const gl = renderer.getContext?.();
  log("_baseScene:ready", {
    hasGL: Boolean(gl),
    version: gl?.getParameter?.(gl.VERSION) || "unknown",
    renderer: gl?.getParameter?.(gl.RENDERER) || "unknown",
  });
  return { scene, camera, renderer, root };
}

function draw2dFallbackBrain(canvas, title, subtitle) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width || 360;
  const h = canvas.height || 240;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#060708";
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "rgba(230,235,240,0.88)";
  ctx.font = "13px -apple-system, Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(title, w / 2, h / 2 - 8);
  ctx.fillStyle = "rgba(150,160,175,0.9)";
  ctx.font = "11px -apple-system, Inter, sans-serif";
  ctx.fillText(subtitle, w / 2, h / 2 + 12);
}

export function mountLoadingBrainCanvas(canvas, options = {}) {
  if (!canvas) return () => {};

  const viewport = resolveViewport(canvas);

  const motionSpeed = Number(options.motionSpeed ?? 0.22);
  const fitMargin = Number(options.fitMargin ?? 1.16);

  const baseYaw = Number(options.baseYaw ?? -0.42);
  const basePitch = Number(options.basePitch ?? -0.08);

  const driftYaw = Number(options.driftYaw ?? 0.045);
  const driftPitch = Number(options.driftPitch ?? 0.02);

  let scene;
  let camera;
  let renderer;
  let root;

  try {
    ({ scene, camera, renderer, root } = _baseScene(canvas));
  } catch (err) {
    error("mountLoadingBrainCanvas:baseScene failed", err);
    draw2dFallbackBrain(canvas, "WebGL unavailable", "Brain preview cannot start — check GPU / browser flags");
    return () => {};
  }

  const brainMat = new THREE.MeshPhysicalMaterial({
    color: options.color ?? 0xcfd6df,
    emissive: options.emissive ?? 0x10151b,
    emissiveIntensity: options.emissiveIntensity ?? 0.2,
    metalness: options.metalness ?? 0.08,
    roughness: options.roughness ?? 0.66,
    clearcoat: options.clearcoat ?? 0.22,
    clearcoatRoughness: options.clearcoatRoughness ?? 0.56,
    reflectivity: options.reflectivity ?? 0.45,
    sheen: options.sheen ?? 0.18,
    sheenColor: new THREE.Color(options.sheenColor ?? 0xf4e7cb),
    sheenRoughness: options.sheenRoughness ?? 0.7,
  });

  // Important: poseGroup is the thing we fit AND animate.
  // That keeps framing stable.
  const poseGroup = new THREE.Group();
  const brainContent = new THREE.Group();
  poseGroup.add(brainContent);
  root.add(poseGroup);

  let meshReady = false;
  let cancelled = false;
  let raf = 0;
  let webglDisposed = false;

  const shutdownWebgl = () => {
    if (webglDisposed) return;
    webglDisposed = true;
    cancelled = true;
    cancelAnimationFrame(raf);
    ro.disconnect();
    _disposeScene(scene, renderer);
  };

  const refitCamera = () => {
    if (!meshReady || cancelled) return;

    // Fit to the actual base hero pose, not a neutral pose.
    poseGroup.rotation.set(basePitch, baseYaw, 0);

    const { width, height } = syncRendererToViewport(renderer, camera, canvas, viewport);
    applyPerspectiveBrainFit(camera, poseGroup, width, height, fitMargin);
  };

  const ro = new ResizeObserver(() => {
    refitCamera();
  });
  ro.observe(viewport || canvas);

  fetchFsaverageMesh()
    .then((mesh) => {
      if (cancelled) return;
      if (!mesh?.lh_coord || !mesh?.rh_coord) {
        warn("mountLoadingBrainCanvas:mesh missing coords");
        shutdownWebgl();
        draw2dFallbackBrain(canvas, "Brain mesh unavailable", "API returned incomplete geometry — see server logs");
        return;
      }

      _buildHemispheres(brainContent, mesh, brainMat, brainMat);
      normalizeBrainGroup(brainContent);

      meshReady = true;
      refitCamera();
      log("mountLoadingBrainCanvas:mesh mounted", { canvasId: canvas.id || "(no-id)" });
    })
    .catch((err) => {
      warn("mountLoadingBrainCanvas:mesh fetch failed", err);
      if (!cancelled) {
        shutdownWebgl();
        draw2dFallbackBrain(canvas, "Brain mesh failed to load", String(err?.message || err).slice(0, 120));
      }
    });

  const failTimer = setTimeout(() => {
    if (cancelled || meshReady) return;
    warn("mountLoadingBrainCanvas:mesh timeout");
    shutdownWebgl();
    draw2dFallbackBrain(canvas, "Brain mesh timed out", "Check network and /api/brain-mesh — not a placeholder 3D brain");
  }, 2500);

  const t0 = performance.now();

  function tick(now) {
    if (cancelled) return;
    raf = requestAnimationFrame(tick);

    if (meshReady) {
      const t = (now - t0) * 0.001;

      // Small premium drift, not full spin.
      poseGroup.rotation.y = baseYaw + Math.sin(t * motionSpeed) * driftYaw;
      poseGroup.rotation.x = basePitch + Math.sin(t * (motionSpeed * 0.82) + 0.9) * driftPitch;

      renderer.render(scene, camera);
    }
  }

  raf = requestAnimationFrame(tick);

  return () => {
    clearTimeout(failTimer);
    shutdownWebgl();
  };
}

export async function mountActivationBrainCanvas(
  canvas,
  {
    values,
    mode = "activation",
    rotationSpeed = 0.22,
    palette = mode === "diff" ? "bwr" : "activation",
  } = {},
) {
  if (!canvas || !values || values.length !== 20484) return () => {};
  let scene;
  let cam;
  let renderer;
  let root;
  try {
    ({ scene, camera: cam, renderer, root } = _baseScene(canvas));
  } catch (err) {
    error("mountActivationBrainCanvas:baseScene failed", err);
    return () => {};
  }
  const viewport = resolveViewport(canvas);
  const mesh = await fetchFsaverageMesh();
  log("mountActivationBrainCanvas:start", { mode, canvasId: canvas.id || "(no-id)" });

  const mix = (a, b, t) => a + (b - a) * t;
  const colorize = (arr, signed, paletteName) => {
    const n = arr.length;
    const absMax = Math.max(1e-6, ...Array.from(arr, (v) => Math.abs(v)));
    const out = new Float32Array(n * 3);
    const neg = [0.55, 0.64, 0.82];
    const mid = [0.12, 0.14, 0.17];
    const pos = [0.86, 0.75, 0.55];
    for (let i = 0; i < n; i += 1) {
      const v = arr[i];
      let r;
      let g;
      let b;
      if (signed) {
        const t = Math.max(-1, Math.min(1, v / absMax));
        if (paletteName === "steel-gold") {
          if (t < 0) {
            const u = Math.abs(t);
            r = mix(mid[0], neg[0], u);
            g = mix(mid[1], neg[1], u);
            b = mix(mid[2], neg[2], u);
          } else {
            const u = t;
            r = mix(mid[0], pos[0], u);
            g = mix(mid[1], pos[1], u);
            b = mix(mid[2], pos[2], u);
          }
        } else {
          [r, g, b] = _bwr(t);
        }
      } else {
        const t = (v + absMax) / (2 * absMax);
        r = 0.16 + t * 0.7;
        g = 0.18 + t * 0.56;
        b = 0.24 + (1 - Math.abs(t - 0.54) * 1.65) * 0.44;
      }
      out[i * 3] = r;
      out[i * 3 + 1] = g;
      out[i * 3 + 2] = b;
    }
    return out;
  };

  const mat = new THREE.MeshPhysicalMaterial({
    vertexColors: true,
    metalness: 0.08,
    roughness: 0.52,
    emissive: 0x07090d,
    emissiveIntensity: 0.18,
    clearcoat: 0.16,
    clearcoatRoughness: 0.6,
    reflectivity: 0.36,
    sheen: 0.08,
    sheenColor: new THREE.Color(0xf2ece1),
    sheenRoughness: 0.72,
  });

  const v = values instanceof Float32Array ? values : Float32Array.from(values);
  const lh = v.subarray(0, 10242);
  const rh = v.subarray(10242);
  const brainContent = new THREE.Group();
  root.add(brainContent);
  const { gL, gR } = _buildHemispheres(brainContent, mesh, mat, mat);
  normalizeBrainGroup(brainContent);
  gL.setAttribute("color", new THREE.BufferAttribute(colorize(lh, mode === "diff", palette), 3));
  gR.setAttribute("color", new THREE.BufferAttribute(colorize(rh, mode === "diff", palette), 3));

  const refit = () => {
    const { width, height } = syncRendererToViewport(renderer, cam, canvas, viewport);
    applyPerspectiveBrainFit(cam, brainContent, width, height);
  };
  refit();
  const ro = new ResizeObserver(() => refit());
  ro.observe(viewport || canvas);

  let raf = 0;
  const t0 = performance.now();
  let cancelled = false;
  function tick(now) {
    if (cancelled) return;
    raf = requestAnimationFrame(tick);
    const t = (now - t0) * 0.001;
    root.rotation.y = t * rotationSpeed;
    root.rotation.x = Math.sin(t * 0.22) * 0.06;
    renderer.render(scene, cam);
  }
  raf = requestAnimationFrame(tick);

  return () => {
    cancelled = true;
    cancelAnimationFrame(raf);
    ro.disconnect();
    _disposeScene(scene, renderer);
  };
}

function lerpView(a, b, t) {
  return {
    yaw: a.yaw + (b.yaw - a.yaw) * t,
    pitch: a.pitch + (b.pitch - a.pitch) * t,
    distScale: a.distScale + (b.distScale - a.distScale) * t,
  };
}

export async function mountHighlightBrainCanvas(
  canvas,
  {
    initialMask = null,
    initialView = { yaw: 0, pitch: 0, distScale: 1 },
  } = {},
) {
  if (!canvas) return { dispose: () => {}, setDimension: () => {} };

  let scene;
  let cam;
  let renderer;
  let root;
  try {
    ({ scene, camera: cam, renderer, root } = _baseScene(canvas));
  } catch (err) {
    error("mountHighlightBrainCanvas:baseScene failed", err);
    draw2dFallbackBrain(canvas, "WebGL unavailable", "Explainer brain needs WebGL");
    return { dispose: () => {}, setDimension: () => {} };
  }
  const viewport = resolveViewport(canvas);
  let lastVpW = 0;
  let lastVpH = 0;

  const brainContent = new THREE.Group();
  root.add(brainContent);

  const mat = new THREE.MeshPhysicalMaterial({
    vertexColors: true,
    metalness: 0.06,
    roughness: 0.56,
    emissive: 0x06080b,
    emissiveIntensity: 0.2,
    clearcoat: 0.12,
    clearcoatRoughness: 0.62,
    reflectivity: 0.32,
  });
  const mesh = await fetchFsaverageMesh();
  log("mountHighlightBrainCanvas:mesh mounted", { canvasId: canvas.id || "(no-id)" });
  const { gL, gR } = _buildHemispheres(brainContent, mesh, mat, mat);
  normalizeBrainGroup(brainContent);

  const colorsL = new Float32Array(10242 * 3);
  const colorsR = new Float32Array(10242 * 3);
  const targetL = new Float32Array(10242 * 3);
  const targetR = new Float32Array(10242 * 3);
  const startL = new Float32Array(10242 * 3);
  const startR = new Float32Array(10242 * 3);
  gL.setAttribute("color", new THREE.BufferAttribute(colorsL, 3));
  gR.setAttribute("color", new THREE.BufferAttribute(colorsR, 3));

  const setTargetFromMask = (maskLike) => {
    const m = maskLike || new Uint8Array(20484);
    for (let i = 0; i < 10242; i += 1) {
      const onL = Boolean(m[i]);
      const onR = Boolean(m[10242 + i]);
      const o = i * 3;
      targetL[o] = onL ? 0.84 : 0.11;
      targetL[o + 1] = onL ? 0.78 : 0.12;
      targetL[o + 2] = onL ? 0.67 : 0.15;
      targetR[o] = onR ? 0.84 : 0.11;
      targetR[o + 1] = onR ? 0.78 : 0.12;
      targetR[o + 2] = onR ? 0.67 : 0.15;
    }
  };

  setTargetFromMask(initialMask);
  colorsL.set(targetL);
  colorsR.set(targetR);
  gL.attributes.color.needsUpdate = true;
  gR.attributes.color.needsUpdate = true;

  let viewA = { ...initialView };
  let viewB = { ...initialView };
  let viewBlendStart = performance.now();

  let colorStartTs = performance.now();
  let active = true;

  const lerpAll = (from, to, out, t) => {
    for (let i = 0; i < out.length; i += 1) out[i] = from[i] + (to[i] - from[i]) * t;
  };

  const currentView = (now) => {
    const u = easeOutQuad((now - viewBlendStart) / VIEW_BLEND_MS);
    return lerpView(viewA, viewB, u);
  };

  const applyViewToCamera = (now) => {
    const el = viewport || canvas.parentElement;
    const r = el?.getBoundingClientRect?.() || canvas.getBoundingClientRect();
    const rw = Math.max(1, Math.floor(r.width));
    const rh = Math.max(1, Math.floor(r.height));
    if (rw !== lastVpW || rh !== lastVpH) {
      lastVpW = rw;
      lastVpH = rh;
      syncRendererToViewport(renderer, cam, canvas, viewport);
    }
    const center = getBrainWorldCenter(brainContent);
    applyPerspectiveBrainFit(cam, brainContent, lastVpW, lastVpH);
    const fitPos = cam.position.clone();
    const v = currentView(now);
    applyOrbitFromFitPosition(cam, center, fitPos, v);
  };

  const animateTo = ({ mask, view }) => {
    startL.set(colorsL);
    startR.set(colorsR);
    setTargetFromMask(mask);
    colorStartTs = performance.now();

    const t0 = performance.now();
    viewA = currentView(t0);
    viewB = { yaw: view.yaw ?? 0, pitch: view.pitch ?? 0, distScale: view.distScale ?? 1 };
    viewBlendStart = t0;
  };

  applyViewToCamera(performance.now());

  let raf = 0;
  function tick(now) {
    if (!active) return;
    raf = requestAnimationFrame(tick);

    const colorT = Math.min(1, (now - colorStartTs) / 480);
    const colorEase = colorT * (2 - colorT);
    lerpAll(startL, targetL, colorsL, colorEase);
    lerpAll(startR, targetR, colorsR, colorEase);
    gL.attributes.color.needsUpdate = true;
    gR.attributes.color.needsUpdate = true;

    root.rotation.y += 0.0026;
    root.rotation.x = Math.sin(now / 1700) * 0.05;

    applyViewToCamera(now);

    renderer.render(scene, cam);
  }
  raf = requestAnimationFrame(tick);

  return {
    setDimension(mask, view) {
      log("mountHighlightBrainCanvas:setDimension", { hasMask: Boolean(mask), view });
      animateTo({ mask, view });
    },
    dispose() {
      active = false;
      cancelAnimationFrame(raf);
      _disposeScene(scene, renderer);
    },
  };
}