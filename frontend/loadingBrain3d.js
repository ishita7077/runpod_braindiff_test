/**
 * Lightweight rotating 3D preview for the loading state.
 * Tries /api/brain-mesh (cached); falls back to an abstract icosahedron.
 */
import * as THREE from "three";

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

export function mountLoadingBrainCanvas(canvas) {
  if (!canvas) return () => {};

  const frame = canvas.closest(".loading-brain-frame");
  const height = 300;

  const scene = new THREE.Scene();
  scene.background = null;

  const camera = new THREE.PerspectiveCamera(38, 1, 1, 520);
  camera.position.set(0, 10, 188);

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  const root = new THREE.Group();
  scene.add(root);

  scene.add(new THREE.AmbientLight(0xaaccff, 0.22));
  const key = new THREE.DirectionalLight(0xffffff, 0.95);
  key.position.set(50, 90, 70);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x44ddcc, 0.35);
  rim.position.set(-60, -20, -80);
  scene.add(rim);

  const brainMat = new THREE.MeshStandardMaterial({
    color: 0x152a28,
    emissive: 0x062e2c,
    emissiveIntensity: 0.55,
    metalness: 0.22,
    roughness: 0.5,
  });

  function addFallbackMesh() {
    const geo = new THREE.IcosahedronGeometry(36, 2);
    const mesh = new THREE.Mesh(geo, brainMat);
    root.add(mesh);
  }

  async function tryBrainMesh() {
    const ac = new AbortController();
    const kill = setTimeout(() => ac.abort(), 8000);
    try {
      const res = await fetch("/api/brain-mesh", { signal: ac.signal });
      if (!res.ok) throw new Error("mesh http");
      const data = await res.json();
      if (!data?.lh_coord || !data?.rh_coord) throw new Error("mesh shape");

      function geom(coord, faces) {
        const flatPos = _flatCoord(coord);
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.BufferAttribute(flatPos, 3));
        g.setIndex(_flatFaces(faces));
        g.computeVertexNormals();
        return g;
      }

      const gL = geom(data.lh_coord, data.lh_faces);
      const gR = geom(data.rh_coord, data.rh_faces);
      const mL = new THREE.Mesh(gL, brainMat);
      mL.position.x = -18;
      const mR = new THREE.Mesh(gR, brainMat);
      mR.position.x = 18;
      root.add(mL, mR);
    } catch {
      addFallbackMesh();
    } finally {
      clearTimeout(kill);
    }
  }

  void tryBrainMesh();

  let raf = 0;
  const t0 = performance.now();
  function tick(now) {
    raf = requestAnimationFrame(tick);
    const t = (now - t0) * 0.001;
    root.rotation.y = t * 0.38;
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
    renderer.dispose();
    scene.traverse((obj) => {
      if (obj.geometry) obj.geometry.dispose();
      const m = obj.material;
      if (m) {
        if (Array.isArray(m)) m.forEach((x) => x.dispose());
        else m.dispose();
      }
    });
  };
}
