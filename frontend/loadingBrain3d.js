/**
 * Shared fsaverage5 brain renderer for loading, landing hero, explainer, and demo visuals.
 */
import * as THREE from "three";

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

function _buildHemispheres(root, mesh, materialL, materialR) {
  const gL = _geometry(mesh.lh_coord, mesh.lh_faces);
  const gR = _geometry(mesh.rh_coord, mesh.rh_faces);
  const mL = new THREE.Mesh(gL, materialL);
  const mR = new THREE.Mesh(gR, materialR);
  mL.position.x = -18;
  mR.position.x = 18;
  root.add(mL, mR);
  return { gL, gR, mL, mR };
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
  camera.position.set(0, 10, 240);
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha,
      powerPreference: "low-power",
    });
  } catch (err) {
    error("_baseScene:WebGLRenderer failed", err);
    throw err;
  }
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

function draw2dFallbackBrain(canvas, label = "fallback") {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width || 360;
  const h = canvas.height || 240;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#060708";
  ctx.fillRect(0, 0, w, h);
  const cx = w * 0.5;
  const cy = h * 0.5;
  const rx = w * 0.22;
  const ry = h * 0.34;
  const g = ctx.createLinearGradient(cx - rx * 1.3, cy, cx + rx * 1.3, cy);
  g.addColorStop(0, "rgba(70,110,220,0.8)");
  g.addColorStop(0.5, "rgba(190,190,190,0.65)");
  g.addColorStop(1, "rgba(96,220,190,0.82)");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.ellipse(cx - w * 0.1, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.ellipse(cx + w * 0.1, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "rgba(230,235,240,0.7)";
  ctx.font = "12px -apple-system, Inter, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText("WebGL fallback brain", cx, h - 20);
  ctx.fillStyle = "rgba(150,160,175,0.75)";
  ctx.font = "11px -apple-system, Inter, sans-serif";
  ctx.fillText(label, cx, h - 6);
}

export function mountLoadingBrainCanvas(canvas, options = {}) {
  if (!canvas) return () => {};
  const frame = canvas.closest(".loading-brain-frame");
  const height = options.height || Number(canvas.getAttribute("height")) || 260;
  const rotationSpeed = Number(options.rotationSpeed ?? 0.38);

  let scene;
  let camera;
  let renderer;
  let root;
  try {
    ({ scene, camera, renderer, root } = _baseScene(canvas));
  } catch (err) {
    error("mountLoadingBrainCanvas:baseScene failed, using 2d fallback", err);
    draw2dFallbackBrain(canvas, "mountLoadingBrainCanvas");
    return () => {};
  }
  const brainMat = new THREE.MeshStandardMaterial({
    color: options.color ?? 0x5ca99f,
    emissive: options.emissive ?? 0x174c47,
    emissiveIntensity: options.emissiveIntensity ?? 0.95,
    metalness: 0.18,
    roughness: 0.42,
  });

  function addFallbackMesh() {
    const geo = new THREE.IcosahedronGeometry(36, 2);
    const mesh = new THREE.Mesh(geo, brainMat);
    root.add(mesh);
  }

  let meshMounted = false;
  fetchFsaverageMesh()
    .then((mesh) => {
      if (!mesh?.lh_coord || !mesh?.rh_coord) {
        warn("mountLoadingBrainCanvas:mesh missing coords, using fallback mesh");
        addFallbackMesh();
        return;
      }
      _buildHemispheres(root, mesh, brainMat, brainMat);
      meshMounted = true;
      log("mountLoadingBrainCanvas:mesh mounted", { canvasId: canvas.id || "(no-id)" });
    })
    .catch((err) => {
      warn("mountLoadingBrainCanvas:mesh fetch failed, using fallback mesh", err);
      addFallbackMesh();
    });

  setTimeout(() => {
    if (!meshMounted && root.children.length === 0) {
      warn("mountLoadingBrainCanvas:mesh timeout fallback");
      addFallbackMesh();
    }
  }, 2500);

  let raf = 0;
  const t0 = performance.now();
  function tick(now) {
    raf = requestAnimationFrame(tick);
    const t = (now - t0) * 0.001;
    root.rotation.y = t * rotationSpeed;
    root.rotation.x = Math.sin(t * 0.22) * 0.07;
    const w = Math.max(200, frame?.clientWidth || canvas.clientWidth || 320);
    camera.aspect = w / height;
    camera.updateProjectionMatrix();
    renderer.setSize(w, height, false);
    renderer.render(scene, camera);
  }
  raf = requestAnimationFrame(tick);

  return () => {
    cancelAnimationFrame(raf);
    _disposeScene(scene, renderer);
  };
}

export async function mountActivationBrainCanvas(
  canvas,
  {
    values,
    mode = "activation",
    height = 260,
    camera = { x: 0, y: 10, z: 240 },
    target = { x: 0, y: 0, z: 0 },
    rotationSpeed = 0.22,
  } = {},
) {
  if (!canvas || !values || values.length !== 20484) return () => {};
  const { scene, camera: cam, renderer, root } = _baseScene(canvas);
  cam.position.set(camera.x, camera.y, camera.z);
  const targetV = new THREE.Vector3(target.x, target.y, target.z);
  const mesh = await fetchFsaverageMesh();
  log("mountActivationBrainCanvas:start", { mode, canvasId: canvas.id || "(no-id)" });

  const colorize = (arr, signed) => {
    const n = arr.length;
    const absMax = Math.max(1e-6, ...Array.from(arr, (v) => Math.abs(v)));
    const out = new Float32Array(n * 3);
    for (let i = 0; i < n; i += 1) {
      const v = arr[i];
      let r;
      let g;
      let b;
      if (signed) {
        [r, g, b] = _bwr(v / absMax);
      } else {
        const t = (v + absMax) / (2 * absMax);
        r = 0.08 + t * 0.92;
        g = 0.18 + (1 - Math.abs(t - 0.55) * 1.7) * 0.55;
        b = 0.2 + (1 - t) * 0.75;
      }
      out[i * 3] = r;
      out[i * 3 + 1] = g;
      out[i * 3 + 2] = b;
    }
    return out;
  };

  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    metalness: 0.08,
    roughness: 0.42,
    emissive: 0x08090b,
    emissiveIntensity: 0.24,
  });

  const v = values instanceof Float32Array ? values : Float32Array.from(values);
  const lh = v.subarray(0, 10242);
  const rh = v.subarray(10242);
  const { gL, gR } = _buildHemispheres(root, mesh, mat, mat);
  gL.setAttribute("color", new THREE.BufferAttribute(colorize(lh, mode === "diff"), 3));
  gR.setAttribute("color", new THREE.BufferAttribute(colorize(rh, mode === "diff"), 3));

  let raf = 0;
  const t0 = performance.now();
  const frame = canvas.parentElement;
  function tick(now) {
    raf = requestAnimationFrame(tick);
    const t = (now - t0) * 0.001;
    root.rotation.y = t * rotationSpeed;
    root.rotation.x = Math.sin(t * 0.22) * 0.06;
    const w = Math.max(220, frame?.clientWidth || canvas.clientWidth || 320);
    cam.aspect = w / height;
    cam.lookAt(targetV);
    cam.updateProjectionMatrix();
    renderer.setSize(w, height, false);
    renderer.render(scene, cam);
  }
  raf = requestAnimationFrame(tick);

  return () => {
    cancelAnimationFrame(raf);
    _disposeScene(scene, renderer);
  };
}

export async function mountHighlightBrainCanvas(
  canvas,
  {
    initialMask = null,
    height = 300,
    initialCamera = { x: 50, y: 10, z: 0 },
    initialTarget = { x: 0, y: 0, z: 0 },
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
    draw2dFallbackBrain(canvas, "mountHighlightBrainCanvas");
    return { dispose: () => {}, setDimension: () => {} };
  }
  cam.position.set(initialCamera.x, initialCamera.y, initialCamera.z);
  const targetV = new THREE.Vector3(initialTarget.x, initialTarget.y, initialTarget.z);
  const mesh = await fetchFsaverageMesh();
  log("mountHighlightBrainCanvas:mesh mounted", { canvasId: canvas.id || "(no-id)" });

  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    metalness: 0.04,
    roughness: 0.46,
    emissive: 0x050607,
    emissiveIntensity: 0.3,
  });
  const { gL, gR } = _buildHemispheres(root, mesh, mat, mat);
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
      targetL[o] = onL ? 0.35 : 0.12;
      targetL[o + 1] = onL ? 0.78 : 0.12;
      targetL[o + 2] = onL ? 0.72 : 0.12;
      targetR[o] = onR ? 0.35 : 0.12;
      targetR[o + 1] = onR ? 0.78 : 0.12;
      targetR[o + 2] = onR ? 0.72 : 0.12;
    }
  };

  setTargetFromMask(initialMask);
  colorsL.set(targetL);
  colorsR.set(targetR);
  gL.attributes.color.needsUpdate = true;
  gR.attributes.color.needsUpdate = true;

  let cameraFrom = cam.position.clone();
  let cameraTo = cam.position.clone();
  let targetFrom = targetV.clone();
  let targetTo = targetV.clone();
  let cameraStartTs = performance.now();
  let colorStartTs = performance.now();
  let active = true;

  const lerpAll = (from, to, out, t) => {
    for (let i = 0; i < out.length; i += 1) out[i] = from[i] + (to[i] - from[i]) * t;
  };

  const animateTo = ({ mask, camera, target }) => {
    startL.set(colorsL);
    startR.set(colorsR);
    setTargetFromMask(mask);
    colorStartTs = performance.now();

    cameraFrom = cam.position.clone();
    cameraTo = new THREE.Vector3(camera.x, camera.y, camera.z);
    targetFrom = targetV.clone();
    targetTo = new THREE.Vector3(target.x, target.y, target.z);
    cameraStartTs = performance.now();
  };

  let raf = 0;
  const frame = canvas.parentElement;
  function tick(now) {
    if (!active) return;
    raf = requestAnimationFrame(tick);

    const colorT = Math.min(1, (now - colorStartTs) / 480);
    const colorEase = colorT * (2 - colorT);
    lerpAll(startL, targetL, colorsL, colorEase);
    lerpAll(startR, targetR, colorsR, colorEase);
    gL.attributes.color.needsUpdate = true;
    gR.attributes.color.needsUpdate = true;

    const camT = Math.min(1, (now - cameraStartTs) / 780);
    const camEase = camT * (2 - camT);
    cam.position.lerpVectors(cameraFrom, cameraTo, camEase);
    targetV.lerpVectors(targetFrom, targetTo, camEase);

    root.rotation.y += 0.0026;
    root.rotation.x = Math.sin(now / 1700) * 0.05;
    const w = Math.max(260, frame?.clientWidth || canvas.clientWidth || 360);
    cam.aspect = w / height;
    cam.lookAt(targetV);
    cam.updateProjectionMatrix();
    renderer.setSize(w, height, false);
    renderer.render(scene, cam);
  }
  raf = requestAnimationFrame(tick);

  return {
    setDimension(mask, cameraCfg, targetCfg = { x: 0, y: 0, z: 0 }) {
      log("mountHighlightBrainCanvas:setDimension", {
        camera: cameraCfg,
        target: targetCfg,
        hasMask: Boolean(mask),
      });
      animateTo({ mask, camera: cameraCfg, target: targetCfg });
    },
    dispose() {
      active = false;
      cancelAnimationFrame(raf);
      _disposeScene(scene, renderer);
    },
  };
}
