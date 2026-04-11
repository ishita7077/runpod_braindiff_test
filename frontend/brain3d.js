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

/** Blue–white–red (matches static matplotlib `bwr`): negative → blue, 0 → white, positive → red. */
function _bwr(t) {
  const x = Math.max(-1, Math.min(1, t));
  if (x <= 0) {
    const u = x + 1;
    return [u, u, 1];
  }
  const u = x;
  return [1, 1 - u, 1 - u];
}

function _medianOfArray(arr) {
  const a = Array.from(arr).sort((p, q) => p - q);
  const mid = Math.floor(a.length / 2);
  return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
}

function _percentileSignedDeviation(arr, med, p) {
  const devs = Array.from(arr, (v) => Math.abs(v - med)).sort((x, y) => x - y);
  if (!devs.length) return 1e-6;
  const idx = Math.min(devs.length - 1, Math.floor((p / 100) * devs.length));
  return Math.max(devs[idx], 1e-6);
}

/** Map HCP label → flat vertex indices (0..20483) for regional highlight. */
function _buildRegionVertexMap(labels) {
  const m = new Map();
  if (!labels?.length) return m;
  for (let i = 0; i < labels.length; i++) {
    const name = labels[i] || "unknown";
    if (!m.has(name)) m.set(name, []);
    m.get(name).push(i);
  }
  return m;
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

function _escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Per-version cortical map: median-centered BWR (same family as static heatmap; comparable A vs B).
 */
function _createScene(container, fullVertexArr, meshPayload, h, opts = {}) {
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
  renderer.toneMappingExposure = 1.28;
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

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 1.0);
  key.position.set(60, 100, 80);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xaabbdd, 0.42);
  fill.position.set(-80, 30, 40);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0x8899aa, 0.28);
  rim.position.set(0, -40, -100);
  scene.add(rim);

  const arr = fullVertexArr instanceof Float32Array ? fullVertexArr : Float32Array.from(fullVertexArr);
  const med = _medianOfArray(arr);
  const vmax = _percentileSignedDeviation(arr, med, 98);
  const lhD = arr.subarray(0, 10242);
  const rhD = arr.subarray(10242);

  function colorHemi(data, flatOffset) {
    const n = data.length;
    const buf = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const t = (data[i] - med) / vmax;
      const [r, g, b] = _bwr(t);
      buf[i * 3] = r;
      buf[i * 3 + 1] = g;
      buf[i * 3 + 2] = b;
    }
    return new THREE.BufferAttribute(buf, 3);
  }

  const mat = new THREE.MeshPhysicalMaterial({
    vertexColors: true,
    metalness: 0.02,
    roughness: 0.48,
    clearcoat: 0.12,
    clearcoatRoughness: 0.45,
  });

  const gL = _geometryFromPayload(meshPayload.lh_coord, meshPayload.lh_faces);
  gL.setAttribute("color", colorHemi(lhD, 0));
  const mL = new THREE.Mesh(gL, mat);
  mL.position.x = -18;
  mL.userData = { hemi: "left", offset: 0 };

  const gR = _geometryFromPayload(meshPayload.rh_coord, meshPayload.rh_faces);
  gR.setAttribute("color", colorHemi(rhD, 10242));
  const mR = new THREE.Mesh(gR, mat);
  mR.position.x = 18;
  mR.userData = { hemi: "right", offset: 10242 };

  const group = new THREE.Group();
  group.add(mL);
  group.add(mR);
  scene.add(group);

  const sceneObj = {
    scene,
    camera,
    renderer,
    controls,
    group,
    mL,
    mR,
    gL,
    gR,
    mat,
    meshes: [mL, mR],
    _colorBackupL: new Float32Array(gL.attributes.color.array),
    _colorBackupR: new Float32Array(gR.attributes.color.array),
    _lastHlKey: "",
  };
  return sceneObj;
}

function _applyRegionHighlight(sceneObj, regionMap, regionName) {
  const cmapL = sceneObj._colorBackupL;
  const cmapR = sceneObj._colorBackupR;
  const attrL = sceneObj.gL.attributes.color;
  const attrR = sceneObj.gR.attributes.color;
  if (!cmapL || !cmapR || !regionMap?.size) return;

  const set = new Set(regionMap.get(regionName) || []);
  if (!set.size) {
    _clearRegionHighlight(sceneObj);
    return;
  }

  const key = regionName || "";
  if (key === sceneObj._lastHlKey) return;
  sceneObj._lastHlKey = key;

  attrL.array.set(cmapL);
  attrR.array.set(cmapR);
  const DIM = 0.26;
  const BOOST = 1.2;
  const TINT = 0.12;

  function paint(buf, base, nVert, flatOffset) {
    for (let li = 0; li < nVert; li++) {
      const flat = flatOffset + li;
      const o = li * 3;
      const on = set.has(flat);
      const r0 = base[o];
      const g0 = base[o + 1];
      const b0 = base[o + 2];
      if (on) {
        buf[o] = Math.min(1, r0 * BOOST + TINT);
        buf[o + 1] = Math.min(1, g0 * BOOST + TINT);
        buf[o + 2] = Math.min(1, b0 * BOOST + TINT);
      } else {
        buf[o] = r0 * DIM;
        buf[o + 1] = g0 * DIM;
        buf[o + 2] = b0 * DIM;
      }
    }
  }

  paint(attrL.array, cmapL, 10242, 0);
  paint(attrR.array, cmapR, 10242, 10242);
  attrL.needsUpdate = true;
  attrR.needsUpdate = true;
}

function _clearRegionHighlight(sceneObj) {
  const cmapL = sceneObj._colorBackupL;
  const cmapR = sceneObj._colorBackupR;
  const attrL = sceneObj.gL.attributes.color;
  const attrR = sceneObj.gR.attributes.color;
  if (cmapL && cmapR) {
    attrL.array.set(cmapL);
    attrR.array.set(cmapR);
    attrL.needsUpdate = true;
    attrR.needsUpdate = true;
  }
  sceneObj._lastHlKey = "";
}

function _setupHover(sceneObj, container, regionMap, atlas, tooltipEl, vertexArr, labelPrimary, comparePair = null) {
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  function onMove(e) {
    const rect = container.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, sceneObj.camera);
    const hits = raycaster.intersectObjects(sceneObj.meshes, false);

    if (!hits.length) {
      _clearRegionHighlight(sceneObj);
      tooltipEl.classList.add("hidden");
      return;
    }

    const hit = hits[0];
    const face = hit.face;
    if (!face) {
      _clearRegionHighlight(sceneObj);
      tooltipEl.classList.add("hidden");
      return;
    }

    const geo = hit.object.geometry;
    const pos = geo.getAttribute("position");
    const hp = hit.point;
    let best = face.a;
    let bestDist = Infinity;
    for (const vi of [face.a, face.b, face.c]) {
      const dx = pos.getX(vi) - hp.x + hit.object.position.x;
      const dy = pos.getY(vi) - hp.y;
      const dz = pos.getZ(vi) - hp.z;
      const d = dx * dx + dy * dy + dz * dz;
      if (d < bestDist) {
        bestDist = d;
        best = vi;
      }
    }

    const offset = hit.object.userData.offset || 0;
    const flatIdx = offset + best;
    const hemiLong = offset === 0 ? "Left hemisphere" : "Right hemisphere";

    const regionName = atlas?.labels?.[flatIdx] || "unknown";
    const dimKeys = atlas?.dimensions?.[regionName] || [];
    const dimNames = dimKeys.map((k) => DIM_LABELS[k] || k).join(" · ") || "—";

    const regionVerts = regionMap.get(regionName);
    if (regionName && regionVerts?.length) {
      _applyRegionHighlight(sceneObj, regionMap, regionName);
    } else {
      _clearRegionHighlight(sceneObj);
    }

    const val = vertexArr[flatIdx] ?? 0;
    const cp = comparePair;
    const otherRow =
      cp && cp.arr?.length === 20484
        ? `<div class="tt-stat"><span class="tt-stat-k">${_escapeHtml(cp.label)}</span><span class="tt-stat-v">${cp.arr[flatIdx]?.toFixed(4) ?? "—"}</span></div>`
        : "";

    tooltipEl.innerHTML =
      `<div class="tt-card">` +
      `<div class="tt-region-name">${_escapeHtml(regionName)}</div>` +
      `<div class="tt-region-meta"><span class="tt-hemi-pill">${hemiLong}</span></div>` +
      `<div class="tt-dims">${_escapeHtml(dimNames)}</div>` +
      `<div class="tt-stat-grid">` +
      `<div class="tt-stat"><span class="tt-stat-k">${_escapeHtml(labelPrimary)}</span><span class="tt-stat-v">${val.toFixed(4)}</span></div>` +
      otherRow +
      `</div></div>`;
    tooltipEl.classList.remove("hidden");
    const wrap = container.closest(".brain-dual-wrap");
    const wr = wrap ? wrap.getBoundingClientRect() : { left: 0, top: 0 };
    tooltipEl.style.left = `${e.clientX - wr.left + 14}px`;
    tooltipEl.style.top = `${e.clientY - wr.top - 10}px`;
  }

  function onLeave() {
    _clearRegionHighlight(sceneObj);
    tooltipEl.classList.add("hidden");
  }

  container.addEventListener("mousemove", onMove);
  container.addEventListener("mouseleave", onLeave);
  return () => {
    container.removeEventListener("mousemove", onMove);
    container.removeEventListener("mouseleave", onLeave);
    _clearRegionHighlight(sceneObj);
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
  renderer.toneMappingExposure = 1.28;
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.enablePan = false;
  controls.minDistance = 110;
  controls.maxDistance = 320;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.5;

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 1.0);
  key.position.set(60, 100, 80);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xaabbdd, 0.42);
  fill.position.set(-80, 30, 40);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0x8899aa, 0.28);
  rim.position.set(0, -40, -100);
  scene.add(rim);

  function colorAttr(delta) {
    const n = delta.length;
    const buf = new Float32Array(n * 3);
    for (let i = 0; i < n; i += 1) {
      const [r, g, b] = _bwr(delta[i] / vmax);
      buf[i * 3] = r;
      buf[i * 3 + 1] = g;
      buf[i * 3 + 2] = b;
    }
    return new THREE.BufferAttribute(buf, 3);
  }

  const mat = new THREE.MeshPhysicalMaterial({
    vertexColors: true,
    metalness: 0.02,
    roughness: 0.48,
    clearcoat: 0.12,
    clearcoatRoughness: 0.45,
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

  const regionMap = _buildRegionVertexMap(atlas?.labels);
  const sceneObj = {
    scene,
    camera,
    renderer,
    controls,
    mL,
    mR,
    gL,
    gR,
    mat,
    meshes: [mL, mR],
    _colorBackupL: new Float32Array(gL.attributes.color.array),
    _colorBackupR: new Float32Array(gR.attributes.color.array),
    _lastHlKey: "",
  };

  const cleanHover = atlas && tooltipEl
    ? _setupHover(sceneObj, container, regionMap, atlas, tooltipEl, arr, "Contrast (B − A)", null)
    : null;

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

  const h = 420;
  const regionMap = _buildRegionVertexMap(atlas?.labels);
  const sceneA = _createScene(containerA, arrA, meshPayload, h, { slave: false });
  const sceneB = _createScene(containerB, arrB, meshPayload, h, { slave: true });

  const cleanHoverA = atlas && tooltipEl
    ? _setupHover(sceneA, containerA, regionMap, atlas, tooltipEl, arrA, "Version A", { arr: arrB, label: "Version B" })
    : null;
  const cleanHoverB = atlas && tooltipEl
    ? _setupHover(sceneB, containerB, regionMap, atlas, tooltipEl, arrB, "Version B", { arr: arrA, label: "Version A" })
    : null;

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
