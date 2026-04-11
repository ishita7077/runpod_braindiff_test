/**
 * fsaverage5 brain viewer (Three.js). Default: one WebGL context (contrast map).
 * Optional: dual viewers for Version A / B side by side (2× WebGL).
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

let _meshPayload = null;
let _atlasPayload = null;

export async function fetchBrainMesh() {
  if (_meshPayload) return _meshPayload;
  const res = await fetch("/api/brain-mesh");
  if (!res.ok) throw new Error(`brain-mesh ${res.status}`);
  _meshPayload = await res.json();
  return _meshPayload;
}

export async function fetchVertexAtlas() {
  if (_atlasPayload) return _atlasPayload;
  const res = await fetch("/api/vertex-atlas");
  if (!res.ok) throw new Error(`vertex-atlas ${res.status}`);
  _atlasPayload = await res.json();
  return _atlasPayload;
}

/** Decode API `vertex_*_b64` (little-endian float32) into Float32Array length 20484. */
export function decodeVertexF32B64(b64) {
  if (!b64 || typeof b64 !== "string") return null;
  try {
    const binary = atob(b64);
    const len = binary.length;
    if (len < 4 || len % 4 !== 0) return null;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
    const arr = new Float32Array(bytes.buffer, 0, len / 4);
    return arr.length === 20484 ? arr : null;
  } catch {
    return null;
  }
}

function _percentileAbs(arr, p) {
  const a = Array.from(arr).map((x) => Math.abs(x)).sort((x, y) => x - y);
  if (!a.length) return 1e-6;
  const idx = Math.min(a.length - 1, Math.floor((p / 100) * a.length));
  return Math.max(a[idx], 1e-6);
}

const DIM_LABELS = {
  personal_resonance: "Self-Relevance",
  social_thinking: "Social Thinking",
  brain_effort: "Brain Effort",
  language_depth: "Language Depth",
  gut_reaction: "Gut Reaction",
};

function _sequential(t) {
  const x = Math.max(0, Math.min(1, t));
  if (x < 0.15) return [0.06, 0.06, 0.08];
  if (x < 0.5) {
    const u = (x - 0.15) / 0.35;
    return [0.08 + 0.42 * u, 0.08 + 0.18 * u, 0.12 + 0.08 * u];
  }
  const u = (x - 0.5) / 0.5;
  return [0.5 + 0.45 * u, 0.26 + 0.6 * u, 0.2 + 0.35 * u];
}

function _coolwarm(t) {
  const x = Math.max(-1, Math.min(1, t));
  if (x < 0) {
    const u = -x;
    return [0.2 + 0.2 * u, 0.35 + 0.25 * u, 0.75 + 0.2 * u];
  }
  const u = x;
  return [0.85 + 0.12 * u, 0.28 + 0.2 * u, 0.22 + 0.12 * u];
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

function _geometryFromPayload(coord, faces) {
  const flatPos = _flatCoord(coord);
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.BufferAttribute(flatPos, 3));
  geom.setIndex(_flatFaces(faces));
  geom.computeVertexNormals();
  return geom;
}

let _dispose = null;
let _setHemisphere = null;

export function disposeBrainViewer() {
  if (typeof _dispose === "function") {
    _dispose();
    _dispose = null;
  }
  _setHemisphere = null;
}

export function setBrainHemisphere(mode) {
  if (_setHemisphere) _setHemisphere(mode);
}

function _createScene(container, vertexData, meshPayload, vmax, label, h, opts = {}) {
  const slave = Boolean(opts.slave);
  const w = Math.max(280, container.clientWidth || 400);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);

  const camera = new THREE.PerspectiveCamera(36, w / h, 1, 600);
  camera.position.set(0, 20, 200);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(w, h);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.5;
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = !slave;
  controls.dampingFactor = 0.06;
  controls.enablePan = false;
  controls.minDistance = 110;
  controls.maxDistance = 320;
  controls.autoRotate = !slave;
  controls.autoRotateSpeed = 0.5;
  if (slave) {
    controls.enabled = false;
  }

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const key = new THREE.DirectionalLight(0xffffff, 1.2);
  key.position.set(60, 100, 80);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xaabbdd, 0.5);
  fill.position.set(-80, 30, 40);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0x8899aa, 0.35);
  rim.position.set(0, -40, -100);
  scene.add(rim);

  const arr = vertexData instanceof Float32Array ? vertexData : Float32Array.from(vertexData);
  const lhD = arr.subarray(0, 10242);
  const rhD = arr.subarray(10242);

  function colorAttr(data) {
    const n = data.length;
    const buf = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const [r, g, b] = _sequential(Math.abs(data[i]) / vmax);
      buf[i * 3] = r;
      buf[i * 3 + 1] = g;
      buf[i * 3 + 2] = b;
    }
    return new THREE.BufferAttribute(buf, 3);
  }

  const mat = new THREE.MeshPhysicalMaterial({
    vertexColors: true,
    metalness: 0.05,
    roughness: 0.38,
    clearcoat: 0.3,
    clearcoatRoughness: 0.3,
  });

  const gL = _geometryFromPayload(meshPayload.lh_coord, meshPayload.lh_faces);
  gL.setAttribute("color", colorAttr(lhD));
  const mL = new THREE.Mesh(gL, mat);
  mL.position.x = -18;
  mL.userData = { hemi: "left", offset: 0 };

  const gR = _geometryFromPayload(meshPayload.rh_coord, meshPayload.rh_faces);
  gR.setAttribute("color", colorAttr(rhD));
  const mR = new THREE.Mesh(gR, mat);
  mR.position.x = 18;
  mR.userData = { hemi: "right", offset: 10242 };

  const group = new THREE.Group();
  group.add(mL);
  group.add(mR);
  scene.add(group);

  return { scene, camera, renderer, controls, group, mL, mR, gL, gR, mat, meshes: [mL, mR] };
}

function _setupHover(sceneObj, container, vertexDataArr, atlas, tooltipEl, label) {
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  function onMove(e) {
    const rect = container.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, sceneObj.camera);
    const hits = raycaster.intersectObjects(sceneObj.meshes, false);

    if (!hits.length) {
      tooltipEl.classList.add("hidden");
      return;
    }

    const hit = hits[0];
    const face = hit.face;
    if (!face) { tooltipEl.classList.add("hidden"); return; }

    const geo = hit.object.geometry;
    const pos = geo.getAttribute("position");
    const hp = hit.point;
    let best = face.a, bestDist = Infinity;
    for (const vi of [face.a, face.b, face.c]) {
      const dx = pos.getX(vi) - hp.x + hit.object.position.x;
      const dy = pos.getY(vi) - hp.y;
      const dz = pos.getZ(vi) - hp.z;
      const d = dx * dx + dy * dy + dz * dz;
      if (d < bestDist) { bestDist = d; best = vi; }
    }

    const offset = hit.object.userData.offset || 0;
    const flatIdx = offset + best;
    const hemi = offset === 0 ? "L" : "R";

    const regionName = atlas?.labels?.[flatIdx] || "unknown";
    const dimKeys = atlas?.dimensions?.[regionName] || [];
    const dimNames = dimKeys.map((k) => DIM_LABELS[k] || k).join(", ") || "—";
    const val = vertexDataArr[flatIdx] ?? 0;

    tooltipEl.innerHTML =
      `<strong>${regionName}</strong> <span class="tt-hemi">${hemi}</span>` +
      `<div class="tt-row"><span>Dimension</span><span>${dimNames}</span></div>` +
      `<div class="tt-row"><span>${label}</span><span>${val.toFixed(4)}</span></div>`;
    tooltipEl.classList.remove("hidden");
    const wrap = container.closest(".brain-dual-wrap");
    const wr = wrap ? wrap.getBoundingClientRect() : { left: 0, top: 0 };
    tooltipEl.style.left = `${e.clientX - wr.left + 14}px`;
    tooltipEl.style.top = `${e.clientY - wr.top - 10}px`;
  }

  function onLeave() { tooltipEl.classList.add("hidden"); }

  container.addEventListener("mousemove", onMove);
  container.addEventListener("mouseleave", onLeave);
  return () => {
    container.removeEventListener("mousemove", onMove);
    container.removeEventListener("mouseleave", onLeave);
  };
}

/**
 * Single viewer: signed contrast (B − A) on one mesh, one WebGL context.
 */
export function mountBrainViewer(container, vertexDelta, meshPayload, atlas, tooltipEl) {
  disposeBrainViewer();
  if (!container || !vertexDelta || !meshPayload?.lh_coord) return;

  const arr = vertexDelta instanceof Float32Array ? vertexDelta : Float32Array.from(vertexDelta);
  if (arr.length !== 20484) return;

  const vmax = _percentileAbs(arr, 98);
  const lhD = arr.subarray(0, 10242);
  const rhD = arr.subarray(10242);

  const w = Math.max(320, container.clientWidth || 640);
  const h = 420;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);

  const camera = new THREE.PerspectiveCamera(36, w / h, 1, 600);
  camera.position.set(0, 20, 200);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(w, h);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.5;
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.enablePan = false;
  controls.minDistance = 110;
  controls.maxDistance = 320;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.5;

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  const key = new THREE.DirectionalLight(0xffffff, 1.2);
  key.position.set(60, 100, 80);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xaabbdd, 0.5);
  fill.position.set(-80, 30, 40);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0x8899aa, 0.35);
  rim.position.set(0, -40, -100);
  scene.add(rim);

  function colorAttr(delta) {
    const n = delta.length;
    const buf = new Float32Array(n * 3);
    for (let i = 0; i < n; i += 1) {
      const [r, g, b] = _coolwarm(delta[i] / vmax);
      buf[i * 3] = r;
      buf[i * 3 + 1] = g;
      buf[i * 3 + 2] = b;
    }
    return new THREE.BufferAttribute(buf, 3);
  }

  const mat = new THREE.MeshPhysicalMaterial({
    vertexColors: true,
    metalness: 0.05,
    roughness: 0.38,
    clearcoat: 0.3,
    clearcoatRoughness: 0.3,
  });

  const gL = _geometryFromPayload(meshPayload.lh_coord, meshPayload.lh_faces);
  gL.setAttribute("color", colorAttr(lhD));
  const mL = new THREE.Mesh(gL, mat);
  mL.position.x = -18;
  mL.userData = { hemi: "left", offset: 0 };

  const gR = _geometryFromPayload(meshPayload.rh_coord, meshPayload.rh_faces);
  gR.setAttribute("color", colorAttr(rhD));
  const mR = new THREE.Mesh(gR, mat);
  mR.position.x = 18;
  mR.userData = { hemi: "right", offset: 10242 };

  const group = new THREE.Group();
  group.add(mL);
  group.add(mR);
  scene.add(group);

  const sceneObj = { scene, camera, renderer, controls, mL, mR, gL, gR, mat, meshes: [mL, mR] };

  const cleanHover = atlas && tooltipEl ? _setupHover(sceneObj, container, arr, atlas, tooltipEl, "Contrast (B−A)") : null;

  _setHemisphere = (mode) => {
    mL.visible = mode === "both" || mode === "left";
    mR.visible = mode === "both" || mode === "right";
  };
  _setHemisphere("both");

  let rafId = 0;
  function tick() {
    rafId = requestAnimationFrame(tick);
    controls.update();
    renderer.render(scene, camera);
  }
  tick();

  const ro = new ResizeObserver(() => {
    const rw = Math.max(320, container.clientWidth);
    camera.aspect = rw / h;
    camera.updateProjectionMatrix();
    renderer.setSize(rw, h);
  });
  ro.observe(container);

  _dispose = () => {
    _setHemisphere = null;
    cancelAnimationFrame(rafId);
    ro.disconnect();
    cleanHover?.();
    controls.dispose();
    gL.dispose();
    gR.dispose();
    mat.dispose();
    renderer.dispose();
    if (renderer.domElement.parentNode) {
      renderer.domElement.parentNode.removeChild(renderer.domElement);
    }
  };
}

/**
 * Mount dual brain viewers (Version A + Version B) side by side.
 */
export function mountDualBrainViewer(containerA, containerB, vertexA, vertexB, meshPayload, atlas, tooltipEl) {
  disposeBrainViewer();
  if (!containerA || !containerB || !vertexA || !vertexB || !meshPayload?.lh_coord) return;

  const arrA = vertexA instanceof Float32Array ? vertexA : Float32Array.from(vertexA);
  const arrB = vertexB instanceof Float32Array ? vertexB : Float32Array.from(vertexB);
  if (arrA.length !== 20484 || arrB.length !== 20484) return;

  const maxAbsA = _percentileAbs(arrA, 98);
  const maxAbsB = _percentileAbs(arrB, 98);
  const vmax = Math.max(maxAbsA, maxAbsB, 1e-6);

  const h = 420;
  const sceneA = _createScene(containerA, arrA, meshPayload, vmax, "A", h, { slave: false });
  const sceneB = _createScene(containerB, arrB, meshPayload, vmax, "B", h, { slave: true });

  const cleanHoverA = atlas && tooltipEl ? _setupHover(sceneA, containerA, arrA, atlas, tooltipEl, "Version A") : null;
  const cleanHoverB = atlas && tooltipEl ? _setupHover(sceneB, containerB, arrB, atlas, tooltipEl, "Version B") : null;

  _setHemisphere = (mode) => {
    for (const s of [sceneA, sceneB]) {
      s.mL.visible = mode === "both" || mode === "left";
      s.mR.visible = mode === "both" || mode === "right";
    }
  };
  _setHemisphere("both");

  let rafId = 0;
  function tick() {
    rafId = requestAnimationFrame(tick);
    sceneA.controls.update();
    sceneB.controls.target.copy(sceneA.controls.target);
    sceneB.camera.position.copy(sceneA.camera.position);
    sceneB.camera.quaternion.copy(sceneA.camera.quaternion);
    sceneA.renderer.render(sceneA.scene, sceneA.camera);
    sceneB.renderer.render(sceneB.scene, sceneB.camera);
  }
  tick();

  const roA = new ResizeObserver(() => {
    const rw = Math.max(280, containerA.clientWidth);
    sceneA.camera.aspect = rw / h;
    sceneA.camera.updateProjectionMatrix();
    sceneA.renderer.setSize(rw, h);
  });
  roA.observe(containerA);

  const roB = new ResizeObserver(() => {
    const rw = Math.max(280, containerB.clientWidth);
    sceneB.camera.aspect = rw / h;
    sceneB.camera.updateProjectionMatrix();
    sceneB.renderer.setSize(rw, h);
  });
  roB.observe(containerB);

  _dispose = () => {
    _setHemisphere = null;
    cancelAnimationFrame(rafId);
    roA.disconnect();
    roB.disconnect();
    cleanHoverA?.();
    cleanHoverB?.();
    for (const s of [sceneA, sceneB]) {
      s.controls.dispose();
      s.gL.dispose();
      s.gR.dispose();
      s.mat.dispose();
      s.renderer.dispose();
      if (s.renderer.domElement.parentNode) {
        s.renderer.domElement.parentNode.removeChild(s.renderer.domElement);
      }
    }
  };
}
