/**
 * Shared brain viewport: normalized mesh, perspective fit-to-bounds, resize sync.
 * Used by loadingBrain3d.js and brain3d.js (Issue 3D-001–007, TASK-01–05).
 */
import * as THREE from "three";

/** Object-space span after normalize — keeps framing stable across viewers. */
export const BRAIN_TARGET_MAX_DIM = 100;

/**
 * Center dual-hemisphere group at origin and scale uniformly so the bbox
 * max edge equals BRAIN_TARGET_MAX_DIM (replaces fixed ±18 offsets).
 */
export function normalizeBrainGroup(group) {
  const box = new THREE.Box3().setFromObject(group);
  if (box.isEmpty()) {
    return { maxDim: BRAIN_TARGET_MAX_DIM };
  }
  const center = new THREE.Vector3();
  const size = new THREE.Vector3();
  box.getCenter(center);
  box.getSize(size);
  group.position.sub(center);
  const maxDim = Math.max(size.x, size.y, size.z, 1e-6);
  const s = BRAIN_TARGET_MAX_DIM / maxDim;
  group.scale.setScalar(s);
  return { maxDim: BRAIN_TARGET_MAX_DIM };
}

/**
 * Match brain3d._applyBrainCameraFit framing, without OrbitControls (loading / highlight).
 */
export function applyPerspectiveBrainFit(camera, group, width, height, margin = 1.12) {
  const h = Math.max(height, 1);
  const w = Math.max(width, 1);
  camera.aspect = w / h;

  const box = new THREE.Box3().setFromObject(group);
  if (box.isEmpty()) {
    camera.updateProjectionMatrix();
    return;
  }

  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const center = sphere.center.clone();
  const radius = Math.max(sphere.radius, 1e-6);

  const vFov = THREE.MathUtils.degToRad(camera.fov);
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * camera.aspect);

  const distV = (radius * margin) / Math.sin(vFov / 2);
  const distH = (radius * margin) / Math.sin(hFov / 2);
  const dist = Math.max(distV, distH);

  camera.position.set(center.x, center.y, center.z + dist);
  camera.near = Math.max(0.05, dist / 120);
  camera.far = Math.max(800, dist * 28);
  camera.lookAt(center);
  camera.updateProjectionMatrix();
}

/**
 * Small orbit relative to a baseline fit position (radians). Avoids absolute camera literals.
 */
export function applyOrbitFromFitPosition(camera, center, fitPosition, { yaw = 0, pitch = 0, distScale = 1 }) {
  const rel = fitPosition.clone().sub(center);
  const r0 = rel.length();
  if (r0 < 1e-6) return;
  const yaw0 = Math.atan2(rel.x, rel.z);
  const phi0 = Math.acos(Math.min(1, Math.max(-1, rel.y / r0)));
  const r = r0 * distScale;
  const theta = yaw0 + yaw;
  const phi = Math.min(Math.PI - 0.02, Math.max(0.02, phi0 + pitch));
  const sinPhi = Math.sin(phi);
  camera.position.set(
    center.x + r * sinPhi * Math.sin(theta),
    center.y + r * Math.cos(phi),
    center.z + r * sinPhi * Math.cos(theta),
  );
  camera.lookAt(center);
  camera.updateProjectionMatrix();
}

export function getBrainWorldCenter(group) {
  const box = new THREE.Box3().setFromObject(group);
  const center = new THREE.Vector3();
  if (box.isEmpty()) return center.set(0, 0, 0);
  box.getCenter(center);
  return center;
}

/**
 * Sync renderer pixel size + camera aspect from a DOM viewport; returns drawable size.
 */
export function syncRendererToViewport(renderer, camera, canvas, viewportEl) {
  const el = viewportEl || canvas.parentElement;
  const rect = el?.getBoundingClientRect?.() || canvas.getBoundingClientRect();
  const w = Math.max(1, Math.floor(rect.width));
  const h = Math.max(1, Math.floor(rect.height));
  const dprCap = Math.min(window.devicePixelRatio || 1, 2);
  renderer.setPixelRatio(dprCap);
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  return { width: w, height: h };
}

export function pickWebGLPowerPreference() {
  try {
    const coarse = window.matchMedia?.("(pointer: coarse)")?.matches;
    const lowMem = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
    if (coarse || lowMem) return "low-power";
  } catch {
    /* ignore */
  }
  return "high-performance";
}
