/**
 * Real cortical-surface viewer for the audio + video result pages.
 *
 * Loads the fsaverage5 pial mesh from /api/brain-mesh and paints it with
 * real per-vertex contrast values (vertex_delta_b64 = 20484 floats from the
 * worker). When the mesh format isn't fsaverage5_pial (worker shipped
 * without the static asset, fell back to procedural geometry), the viewer
 * still renders the brain shape but skips the per-vertex paint and labels
 * itself "geometry-only" — better than silently lying with sine-wave colors.
 *
 * Per-modality emphasis is applied via the `roiHighlight` parameter:
 *   - audio page passes 'auditory' → boost luminance in temporal-lobe verts
 *   - video page passes 'visual'   → boost luminance in occipital + MT verts
 *
 * Exported singletons (no class needed; we mount one per page):
 *
 *   const cortex = await mountCortex({
 *     canvas, vertexDeltaB64, vertexAB64, vertexBB64,
 *     roiHighlight: 'auditory' | 'visual' | null,
 *   });
 *   cortex.setView('diff');                    // 'diff' | 'a' | 'b'
 *   cortex.setHighlightVerts([1234, 5678]);    // emphasize specific verts
 *   cortex.dispose();
 */
import * as THREE from "three";
import { OrbitControls } from "https://unpkg.com/three@0.164.1/examples/jsm/controls/OrbitControls.js";

const MESH_VERTS = 20484; // fsaverage5: 10242 per hemisphere × 2

function decodeFloat32B64(b64) {
  if (!b64 || typeof b64 !== "string") return new Float32Array(0);
  const raw = atob(b64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) buf[i] = raw.charCodeAt(i);
  return new Float32Array(buf.buffer);
}

async function fetchMesh() {
  // Try the Vercel API function first (production), then fall back to the
  // static asset which the Python dev-server exposes at /assets/brain-mesh.json.
  // This means the real fsaverage5 mesh renders on localhost too — no black void.
  const candidates = ["/api/brain-mesh", "/assets/brain-mesh.json"];
  for (const url of candidates) {
    try {
      const res = await fetch(url, { cache: "force-cache" });
      if (!res.ok) continue;
      const payload = await res.json();
      if (payload && payload.lh_coord && payload.rh_coord) return payload;
    } catch (_) {
      // try next candidate
    }
  }
  throw new Error("brain-mesh unavailable on all endpoints");
}

function buildGeometry(meshPayload) {
  const lh = meshPayload.lh_coord;
  const rh = meshPayload.rh_coord;
  const lhFaces = meshPayload.lh_faces;
  const rhFaces = meshPayload.rh_faces;
  const totalVerts = lh.length + rh.length;
  const positions = new Float32Array(totalVerts * 3);
  for (let i = 0; i < lh.length; i += 1) {
    positions[i * 3 + 0] = lh[i][0];
    positions[i * 3 + 1] = lh[i][1];
    positions[i * 3 + 2] = lh[i][2];
  }
  for (let i = 0; i < rh.length; i += 1) {
    const off = (lh.length + i) * 3;
    positions[off + 0] = rh[i][0];
    positions[off + 1] = rh[i][1];
    positions[off + 2] = rh[i][2];
  }
  const indices = [];
  for (const f of lhFaces) indices.push(f[0], f[1], f[2]);
  const lhVertCount = lh.length;
  for (const f of rhFaces) indices.push(f[0] + lhVertCount, f[1] + lhVertCount, f[2] + lhVertCount);
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  // Auto-center + scale so the brain always lands at a comfortable size,
  // independent of whether the mesh is real fsaverage5 (extents ~70mm) or
  // the procedural fallback (extents ~1).
  geometry.computeBoundingSphere();
  const sphere = geometry.boundingSphere;
  if (sphere) {
    const center = sphere.center;
    const scale = 1.4 / sphere.radius;
    const pos = geometry.attributes.position;
    for (let i = 0; i < pos.count; i += 1) {
      pos.setXYZ(
        i,
        (pos.getX(i) - center.x) * scale,
        (pos.getY(i) - center.y) * scale,
        (pos.getZ(i) - center.z) * scale
      );
    }
    pos.needsUpdate = true;
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
  }
  return { geometry, vertCount: totalVerts, lhVertCount };
}

function roiMask(meshPayload, kind, lhVertCount, totalVerts) {
  // Heuristic spatial masks. We don't have HCP-MMP1.0 atlas labels available
  // on the static client side (those live in atlases/*.annot, server-side).
  // So we approximate the relevant lobes from vertex coordinates instead:
  //   - auditory: superior temporal sulcus / Heschl's region
  //                lateral, roughly mid-AP, lower in y
  //   - visual:   occipital pole + MT
  //                posterior (low z), low-to-mid lateral
  // It's an approximation, not an atlas-mapped ROI. We label it as such in
  // the UI hint so the user knows the highlight is "approximate" not exact.
  if (!kind) return null;
  const lh = meshPayload.lh_coord;
  const rh = meshPayload.rh_coord;
  const mask = new Uint8Array(totalVerts);
  function add(idx, coords) {
    for (let i = 0; i < coords.length; i += 1) {
      const x = coords[i][0];
      const y = coords[i][1];
      const z = coords[i][2];
      if (kind === "auditory") {
        // Lateral surface of the temporal lobe — high |x|, low-to-mid y, low z.
        if (Math.abs(x) > 38 && y > -20 && y < 40 && z < 20) mask[idx + i] = 1;
      } else if (kind === "visual") {
        // Occipital pole + MT — y < -50 (posterior), |z| moderate.
        if (y < -50) mask[idx + i] = 1;
      }
    }
  }
  add(0, lh);
  add(lhVertCount, rh);
  return mask;
}

function paintColors(geometry, vertexDelta, view, roi, themeIsDark) {
  const colorAttr = geometry.attributes.color;
  if (!colorAttr) return;
  const baseDark = [0.42, 0.39, 0.35];
  const baseLight = [0.78, 0.74, 0.66];
  const [bR, bG, bB] = themeIsDark ? baseDark : baseLight;
  const aColor = [0.29, 0.47, 0.67];   // slate
  const bColor = [0.88, 0.29, 0.18];   // vermillion
  const count = vertexDelta && vertexDelta.length ? vertexDelta.length : geometry.attributes.position.count;
  // Compute a robust scale factor for the delta range so weak signals
  // still paint visibly without saturating on outliers.
  let absMax = 0;
  if (vertexDelta && vertexDelta.length) {
    for (let i = 0; i < count; i += 1) {
      const v = Math.abs(vertexDelta[i]);
      if (v > absMax) absMax = v;
    }
  }
  const scale = absMax > 0 ? 1 / absMax : 1;
  for (let i = 0; i < geometry.attributes.position.count; i += 1) {
    let r = bR, g = bG, b = bB;
    if (i < count && vertexDelta && vertexDelta.length) {
      const v = vertexDelta[i] * scale;
      if (v >= 0) {
        const t = Math.min(1, v);
        r = bR + t * (bColor[0] - bR);
        g = bG + t * (bColor[1] - bG);
        b = bB + t * (bColor[2] - bB);
      } else {
        const t = Math.min(1, -v);
        r = bR + t * (aColor[0] - bR);
        g = bG + t * (aColor[1] - bG);
        b = bB + t * (aColor[2] - bB);
      }
    }
    if (roi && roi[i]) {
      // Per-modality emphasis: brighten the relevant ROI verts so the user's
      // eye lands on the right neighbourhood without obscuring the contrast.
      r = Math.min(1, r * 1.18);
      g = Math.min(1, g * 1.14);
      b = Math.min(1, b * 1.10);
    }
    colorAttr.setXYZ(i, r, g, b);
  }
  colorAttr.needsUpdate = true;
}

export async function mountCortex({
  canvas,
  vertexDeltaB64,
  vertexAB64,
  vertexBB64,
  roiHighlight = null,
}) {
  if (!canvas) throw new Error("cortex-viewer: canvas required");

  let meshPayload;
  try {
    meshPayload = await fetchMesh();
  } catch (err) {
    console.warn("cortex-viewer: brain-mesh fetch failed, viewer disabled", err);
    return { dispose() {}, setView() {}, isReal: false, format: null };
  }
  const isReal = meshPayload.format === "fsaverage5_pial";
  const { geometry, vertCount, lhVertCount } = buildGeometry(meshPayload);
  const colors = new Float32Array(vertCount * 3);
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));

  const VIEW_DELTAS = {
    diff: decodeFloat32B64(vertexDeltaB64),
    a: decodeFloat32B64(vertexAB64),
    b: decodeFloat32B64(vertexBB64),
  };
  // For the per-side views we don't have a "delta" — paint magnitude only,
  // leaning toward the side's color.
  if (VIEW_DELTAS.a.length) {
    const arr = new Float32Array(VIEW_DELTAS.a.length);
    for (let i = 0; i < arr.length; i += 1) arr[i] = -Math.abs(VIEW_DELTAS.a[i]);
    VIEW_DELTAS.a = arr;
  }
  if (VIEW_DELTAS.b.length) {
    const arr = new Float32Array(VIEW_DELTAS.b.length);
    for (let i = 0; i < arr.length; i += 1) arr[i] = Math.abs(VIEW_DELTAS.b[i]);
    VIEW_DELTAS.b = arr;
  }

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(0, 0.16, 5.3);
  // Set size immediately — don't wait for ResizeObserver which fires async
  // and leaves a 300×150 default canvas for the first rendered frame.
  {
    const p = canvas.parentElement;
    if (p) {
      const r = p.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) {
        renderer.setSize(r.width, r.height, false);
        camera.aspect = r.width / r.height;
        camera.updateProjectionMatrix();
      }
    }
  }
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.enablePan = false;
  controls.minDistance = 2.5;
  controls.maxDistance = 7;
  controls.rotateSpeed = 0.8;
  controls.zoomSpeed = 1.6;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x40362e, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 2.4);
  key.position.set(3, 4, 5);
  scene.add(key);

  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.7,
    metalness: 0.04,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.rotation.set(0.05, -0.45, 0);
  scene.add(mesh);

  const roi = roiMask(meshPayload, roiHighlight, lhVertCount, vertCount);
  let currentView = "diff";

  function repaint(view) {
    const themeIsDark = document.documentElement.dataset.theme === "dark";
    paintColors(geometry, VIEW_DELTAS[view] || VIEW_DELTAS.diff, view, roi, themeIsDark);
  }
  repaint(currentView);

  const ro = new ResizeObserver(() => {
    const rect = canvas.parentElement.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    renderer.setSize(rect.width, rect.height, false);
    camera.aspect = rect.width / rect.height;
    camera.updateProjectionMatrix();
  });
  ro.observe(canvas.parentElement);

  let raf = 0;
  let disposed = false;
  function loop() {
    if (disposed) return;
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(loop);
  }
  loop();

  // Re-paint on theme flip so the base palette flips too.
  function onTheme() { repaint(currentView); }
  window.addEventListener("braindiff:theme", onTheme);

  return {
    isReal,
    format: meshPayload.format,
    setView(view) {
      currentView = view in VIEW_DELTAS ? view : "diff";
      repaint(currentView);
    },
    reset() {
      camera.position.set(0, 0.16, 5.3);
      controls.target.set(0, 0, 0);
      mesh.rotation.set(0.05, -0.45, 0);
      controls.update();
    },
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("braindiff:theme", onTheme);
      renderer.dispose();
      geometry.dispose();
      material.dispose();
    },
  };
}
