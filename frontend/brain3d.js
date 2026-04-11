/**
 * WebGL fsaverage5 brain viewer (Three.js). Falls back to PNG if load fails.
 */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

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
  if (x < 0) {
    const u = -x;
    return [0.25 + 0.15 * u, 0.4 + 0.15 * u, 0.75 + 0.2 * u];
  }
  const u = x;
  return [0.8 + 0.15 * u, 0.25 + 0.15 * u, 0.18 + 0.1 * u];
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
  const h = 480;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x000000);

  const camera = new THREE.PerspectiveCamera(38, w / h, 1, 600);
  camera.position.set(0, 20, 210);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(w, h);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.enablePan = false;
  controls.minDistance = 120;
  controls.maxDistance = 350;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.6;

  scene.add(new THREE.AmbientLight(0x404060, 0.5));
  const key = new THREE.DirectionalLight(0xffffff, 0.9);
  key.position.set(60, 100, 80);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x8899cc, 0.4);
  fill.position.set(-80, 30, 40);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0x556688, 0.3);
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
    metalness: 0.08,
    roughness: 0.55,
    clearcoat: 0.15,
    clearcoatRoughness: 0.4,
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
