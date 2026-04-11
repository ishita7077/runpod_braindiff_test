/**
 * fsaverage5 brain viewer (Three.js). Default UI: dual A/B surfaces; optional single contrast view.
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

/** Short plain-language gloss for HCP MMP1 area codes (keys = annot core, e.g. "8BL" from L_8BL_ROI). */
const PARCEL_GLOSS = {
  "8BL": "Frontal area 8B — lateral (control / goals)",
  "8Av": "Frontal area 8A — ventral",
  "8C": "Frontal area 8C",
  "46": "Dorsolateral prefrontal cortex (area 46)",
  "p9-46v": "Posterior ventral area 9-46 (effort / control)",
  "a9-46v": "Anterior ventral area 9-46",
  "44": "Inferior frontal — speech production (area 44)",
  "45": "Inferior frontal — language (area 45)",
  OFC: "Orbitofrontal cortex (decision / value)",
  PSL: "Perisylvian language zone",
  STV: "Superior temporal — voice / speech",
  STSdp: "Superior temporal sulcus — dorsal posterior",
  STSvp: "Superior temporal sulcus — ventral posterior",
  "10r": "Frontal pole — self / relevance (10r)",
  "10v": "Ventromedial frontal pole (10v)",
  "9m": "Dorsomedial prefrontal (area 9m)",
  "10d": "Dorsal frontal pole (10d)",
  "32": "Anterior cingulate / medial wall (area 32)",
  "25": "Subgenual frontal / affect (area 25)",
  PGi: "Inferior parietal — integration & social context",
  PGs: "Superior parietal — spatial / social maps",
  TPOJ1: "Temporo-parietal junction (social attention)",
  TPOJ2: "Temporo-parietal junction (social meaning)",
  TPOJ3: "Temporo-parietal junction (extended social)",
  AVI: "Insular cortex — visceral / affect",
  AAIC: "Anterior agranular insula",
  MI: "Mid insula — salience",
  d32: "Cingulate 32 — dorsal division",
  p32: "Cingulate 32 — posterior division",
  s32: "Cingulate 32 — subgenual strip",
  a32pr: "Pregenual anterior 32",
  p32pr: "Posterior 32 (p32pr)",
};

function _humanizeRegionTitle(raw) {
  if (!raw || raw === "unknown" || raw === "???") {
    return {
      title: "Unlabeled cortical location",
      subtitle: "Could not match this point to a named HCP parcel.",
    };
  }
  const m = raw.match(/^(L|R)_(.+)_ROI$/);
  const hemiWord = m ? (m[1] === "L" ? "Left" : "Right") : "";
  const core = m ? m[2] : raw.replace(/_ROI$/, "").replace(/^(L|R)_/, "");
  const gloss = PARCEL_GLOSS[core];
  const plain = core.replace(/_/g, " ");
  const title = gloss
    ? `${hemiWord ? `${hemiWord} · ` : ""}${gloss}`
    : `${hemiWord ? `${hemiWord} · ` : ""}Cortical area ${plain}`;
  return {
    title,
    subtitle: "Standard brain atlas region (HCP-MMP1).",
  };
}

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
let _resetBrainCamera = null;

export function disposeBrainViewer() {
  if (typeof _dispose === "function") {
    _dispose();
    _dispose = null;
  }
  _setHemisphere = null;
  _resetBrainCamera = null;
}

/** Recenters and reframes the mesh (OrbitControls target + distance limits). */
export function resetBrainCamera() {
  if (typeof _resetBrainCamera === "function") _resetBrainCamera();
}

/**
 * Frame the LH+RH group in view using vertical FOV and aspect (handles narrow dual-pane canvases).
 */
function _applyBrainCameraFit(camera, controls, group, margin = 1.14) {
  const box = new THREE.Box3().setFromObject(group);
  if (!box || box.isEmpty()) return;
  const center = new THREE.Vector3();
  const size = new THREE.Vector3();
  box.getCenter(center);
  box.getSize(size);
  const maxDim = Math.max(size.x, size.y, size.z, 1e-6);
  controls.target.copy(center);
  const vFovRad = (camera.fov * Math.PI) / 180;
  const tanHalf = Math.tan(vFovRad / 2);
  const distV = (maxDim * margin) / (2 * tanHalf);
  const halfW = maxDim * 0.5;
  const distH = (halfW * margin) / (Math.max(camera.aspect, 0.2) * tanHalf);
  const dist = Math.max(distV, distH);
  camera.position.set(center.x, center.y + maxDim * 0.08, center.z + dist);
  camera.near = Math.max(0.05, dist / 120);
  camera.far = Math.max(800, dist * 28);
  camera.updateProjectionMatrix();
  controls.minDistance = maxDim * 0.18;
  controls.maxDistance = maxDim * 6.5;
  controls.update();
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

  const camera = new THREE.PerspectiveCamera(36, w / h, 0.05, 2000);
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
  controls.minDistance = 20;
  controls.maxDistance = 800;
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

/**
 * @param {object} hoverOpts
 * @param {"contrast" | "dual"} hoverOpts.mode
 * @param {Float32Array} [hoverOpts.delta] — B−A contrast (single-brain view)
 * @param {Float32Array} [hoverOpts.arrA] — Version A vertex values (dual view)
 * @param {Float32Array} [hoverOpts.arrB] — Version B vertex values (dual view)
 * @param {string} [hoverOpts.labelA] — Short label for Version A text (dual)
 * @param {string} [hoverOpts.labelB] — Short label for Version B text (dual)
 */
function _setupHover(sceneObj, container, regionMap, atlas, tooltipEl, hoverOpts) {
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  const mode = hoverOpts?.mode === "dual" ? "dual" : "contrast";
  const labelA = (hoverOpts?.labelA || "Version A").trim();
  const labelB = (hoverOpts?.labelB || "Version B").trim();

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
    const dimPretty = dimKeys.map((k) => DIM_LABELS[k] || k).join(" · ");

    const regionVerts = regionMap.get(regionName);
    if (regionName && regionVerts?.length) {
      _applyRegionHighlight(sceneObj, regionMap, regionName);
    } else {
      _clearRegionHighlight(sceneObj);
    }

    const human = _humanizeRegionTitle(regionName);

    const explainerDual =
      `<p class="tt-explainer">The bright outline is the <strong>entire</strong> named region; everything else is dimmed so you can see the parcel as a whole.</p>` +
      `<p class="tt-explainer tt-explainer-tight">On <strong>${_escapeHtml(labelA)}</strong> and <strong>${_escapeHtml(labelB)}</strong>, color is hotter or cooler than that version’s <em>own</em> middle value—so you can compare shape between the two brains fairly.</p>`;

    const explainerContrast =
      `<p class="tt-explainer">The bright outline is the <strong>entire</strong> atlas region on the surface.</p>` +
      `<p class="tt-explainer tt-explainer-tight">Colors show <strong>Version B minus Version A</strong> (red = more modeled activity for B, blue = more for A). Same idea as the static multi-view figure below.</p>`;

    const explainer = mode === "dual" ? explainerDual : explainerContrast;

    const dimBlock = dimPretty
      ? `<div class="tt-dims"><span class="tt-dims-k">Themes</span><span class="tt-dims-v">${_escapeHtml(dimPretty)}</span></div>`
      : `<div class="tt-dims tt-dims-muted">Not one of the five headline themes in this app—you can still read the numbers as higher vs lower modeled response in this spot.</div>`;

    let statsBlock = "";
    if (mode === "dual" && hoverOpts.arrA?.length === 20484 && hoverOpts.arrB?.length === 20484) {
      const va = hoverOpts.arrA[flatIdx] ?? 0;
      const vb = hoverOpts.arrB[flatIdx] ?? 0;
      const diff = vb - va;
      statsBlock =
        `<div class="tt-stat-grid">` +
        `<p class="tt-stat-lead">Values at this point</p>` +
        `<div class="tt-stat"><span class="tt-stat-k">${_escapeHtml(labelA)} — normalized</span><span class="tt-stat-v">${va.toFixed(3)}</span></div>` +
        `<div class="tt-stat"><span class="tt-stat-k">${_escapeHtml(labelB)} — normalized</span><span class="tt-stat-v">${vb.toFixed(3)}</span></div>` +
        `<div class="tt-stat tt-stat-em"><span class="tt-stat-k">Difference (B − A)</span><span class="tt-stat-v">${diff >= 0 ? "+" : ""}${diff.toFixed(3)}</span></div>` +
        `</div>` +
        `<p class="tt-stat-foot">Same scaling family as the flat maps. For comparing drafts only—not a clinical or diagnostic score.</p>`;
    } else if (mode === "contrast" && hoverOpts.delta?.length === 20484) {
      const val = hoverOpts.delta[flatIdx] ?? 0;
      statsBlock =
        `<div class="tt-stat-grid">` +
        `<p class="tt-stat-lead">Contrast at this point</p>` +
        `<div class="tt-stat"><span class="tt-stat-k">B minus A (signed)</span><span class="tt-stat-v">${val >= 0 ? "+" : ""}${val.toFixed(3)}</span></div>` +
        `</div>` +
        `<p class="tt-stat-foot">Positive means Version B is modeled higher here; negative means Version A. Matches the static heatmap colors.</p>`;
    } else {
      statsBlock = `<p class="tt-stat-foot">Values unavailable for this view.</p>`;
    }

    tooltipEl.innerHTML =
      `<div class="tt-card">` +
      `<div class="tt-region-title">${_escapeHtml(human.title)}</div>` +
      `<div class="tt-region-sub">${_escapeHtml(human.subtitle)}</div>` +
      `<div class="tt-hemi-row"><span class="tt-hemi-pill">${hemiLong}</span></div>` +
      explainer +
      dimBlock +
      statsBlock +
      `</div>`;
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
 * @param {object} [viewerOpts] reserved for future hover copy
 */
export function mountBrainViewer(container, vertexDelta, meshPayload, atlas, tooltipEl, viewerOpts) {
  void viewerOpts;
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

  const camera = new THREE.PerspectiveCamera(36, w / h, 0.05, 2000);
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
  controls.minDistance = 20;
  controls.maxDistance = 800;
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

  function refitBrain() {
    _applyBrainCameraFit(camera, controls, group);
  }
  refitBrain();
  _resetBrainCamera = refitBrain;

  const regionMap = _buildRegionVertexMap(atlas?.labels);
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

  const cleanHover = atlas && tooltipEl
    ? _setupHover(sceneObj, container, regionMap, atlas, tooltipEl, { mode: "contrast", delta: arr })
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
    _resetBrainCamera = null;
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
 * @param {object} [viewerOpts]
 * @param {string} [viewerOpts.labelA] short label for hover (e.g. truncated input A)
 * @param {string} [viewerOpts.labelB] short label for hover (e.g. truncated input B)
 */
export function mountDualBrainViewer(containerA, containerB, vertexA, vertexB, meshPayload, atlas, tooltipEl, viewerOpts) {
  disposeBrainViewer();
  if (!containerA || !containerB || !vertexA || !vertexB || !meshPayload?.lh_coord) return;

  const arrA = vertexA instanceof Float32Array ? vertexA : Float32Array.from(vertexA);
  const arrB = vertexB instanceof Float32Array ? vertexB : Float32Array.from(vertexB);
  if (arrA.length !== 20484 || arrB.length !== 20484) return;

  const h = 420;
  const regionMap = _buildRegionVertexMap(atlas?.labels);
  const sceneA = _createScene(containerA, arrA, meshPayload, h, { slave: false });
  const sceneB = _createScene(containerB, arrB, meshPayload, h, { slave: true });

  function refitDual() {
    _applyBrainCameraFit(sceneA.camera, sceneA.controls, sceneA.group);
  }
  refitDual();
  _resetBrainCamera = refitDual;

  const dualHoverOpts = {
    mode: "dual",
    arrA,
    arrB,
    labelA: viewerOpts?.labelA || "Version A",
    labelB: viewerOpts?.labelB || "Version B",
  };
  const cleanHoverA = atlas && tooltipEl
    ? _setupHover(sceneA, containerA, regionMap, atlas, tooltipEl, dualHoverOpts)
    : null;
  const cleanHoverB = atlas && tooltipEl
    ? _setupHover(sceneB, containerB, regionMap, atlas, tooltipEl, dualHoverOpts)
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
    _resetBrainCamera = null;
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
