/**
 * WebGL fsaverage5 brain viewer (Three.js). Falls back if mesh load fails.
 */
import * as THREE from "https://unpkg.com/three@0.160.0/build/three.module.js";
import { OrbitControls } from "https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js";

let _meshPayload = null;

export async function fetchBrainMesh() {
  if (_meshPayload) return _meshPayload;
  const res = await fetch("/api/brain-mesh");
  if (!res.ok) throw new Error(`brain-mesh ${res.status}`);
  _meshPayload = await res.json();
  return _meshPayload;
}

function _percentileAbs(arr, p) {
  const a = Array.from(arr).map((x) => Math.abs(x)).sort((x, y) => x - y);
  if (!a.length) return 1e-6;
  const idx = Math.min(a.length - 1, Math.floor((p / 100) * a.length));
  return Math.max(a[idx], 1e-6);
}

function _coolwarm(t) {
  const x = Math.max(-1, Math.min(1, t));
  const c = new THREE.Color();
  if (x < 0) {
    const u = -x;
    c.setRGB(0.15 + 0.1 * u, 0.2 + 0.25 * u, 0.85 + 0.1 * u);
  } else {
    const u = x;
    c.setRGB(0.9 + 0.08 * u, 0.22 + 0.28 * u, 0.18 + 0.2 * u);
  }
  return c;
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
/** @type {((mode: "both" | "left" | "right") => void) | null} */
let _setHemisphere = null;

export function disposeBrainViewer() {
  if (typeof _dispose === "function") {
    _dispose();
    _dispose = null;
  }
  _setHemisphere = null;
}

/** Toggle visible hemispheres (no-op if viewer not mounted). */
export function setBrainHemisphere(mode) {
  if (_setHemisphere) _setHemisphere(mode);
}

/**
 * @param {HTMLElement} container
 * @param {Float32Array|number[]} vertexDelta length 20484
 * @param {object} meshPayload from /api/brain-mesh
 */
export function mountBrainViewer(container, vertexDelta, meshPayload) {
  disposeBrainViewer();
  if (!container || !vertexDelta || !meshPayload?.lh_coord) return;

  const arr = vertexDelta instanceof Float32Array ? vertexDelta : Float32Array.from(vertexDelta);
  if (arr.length !== 20484) return;

  const vmax = _percentileAbs(arr, 98);
  const lhD = arr.subarray(0, 10242);
  const rhD = arr.subarray(10242);

  const w = Math.max(320, container.clientWidth || 800);
  const h = 400;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05060a);

  const camera = new THREE.PerspectiveCamera(42, w / h, 0.1, 500);
  camera.position.set(0, 0, 220);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  const hemi = new THREE.HemisphereLight(0x8899ff, 0x080810, 0.9);
  scene.add(hemi);
  const dir = new THREE.DirectionalLight(0xffffff, 0.55);
  dir.position.set(80, 120, 60);
  scene.add(dir);
  const rim = new THREE.PointLight(0x66ccff, 0.35, 400);
  rim.position.set(-120, 40, 80);
  scene.add(rim);

  function colorAttr(delta) {
    const n = delta.length;
    const buf = new Float32Array(n * 3);
    for (let i = 0; i < n; i += 1) {
      const c = _coolwarm(delta[i] / vmax);
      buf[i * 3] = c.r;
      buf[i * 3 + 1] = c.g;
      buf[i * 3 + 2] = c.b;
    }
    return new THREE.BufferAttribute(buf, 3);
  }

  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    metalness: 0.25,
    roughness: 0.42,
    emissive: new THREE.Color(0x111826),
    emissiveIntensity: 0.45,
  });

  const gL = _geometryFromPayload(meshPayload.lh_coord, meshPayload.lh_faces);
  gL.setAttribute("color", colorAttr(lhD));
  const mL = new THREE.Mesh(gL, mat);
  mL.position.x = -18;

  const gR = _geometryFromPayload(meshPayload.rh_coord, meshPayload.rh_faces);
  gR.setAttribute("color", colorAttr(rhD));
  const mR = new THREE.Mesh(gR, mat);
  mR.position.x = 18;

  const group = new THREE.Group();
  group.add(mL);
  group.add(mR);
  scene.add(group);

  _setHemisphere = (mode) => {
    const both = mode === "both";
    mL.visible = both || mode === "left";
    mR.visible = both || mode === "right";
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
    controls.dispose();
    gL.dispose();
    gR.dispose();
    mat.dispose();
    renderer.dispose();
    if (renderer.domElement.parentNode === container) {
      container.removeChild(renderer.domElement);
    }
  };
}
