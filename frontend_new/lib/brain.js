import * as THREE from "three";

/* ---------------------------------------------------------------------------
   Real fsaverage5 mesh loader (shared cache — one fetch per page).
   Backend endpoint: /api/brain-mesh. Returns { lh_coord, lh_faces, rh_coord, rh_faces }.
   If unavailable, callers fall back to a procedural placeholder.
--------------------------------------------------------------------------- */
let _brainMeshPromise = null;
function fetchBrainMesh(){
  if (_brainMeshPromise) return _brainMeshPromise;
  _brainMeshPromise = (async () => {
    // Try static asset first (CDN-served, no cold-start), fall back to API function.
    for (const url of ['/assets/brain-mesh.json', '/api/brain-mesh']) {
      try {
        const res = await fetch(url);
        if (!res.ok) {
          console.warn('[BrainDiff] fetch', url, 'returned', res.status);
          continue;
        }
        const data = await res.json();
        if (data && data.lh_coord && data.rh_coord) return data;
        console.warn('[BrainDiff] fetch', url, 'payload missing lh_coord/rh_coord');
      } catch(err) {
        console.warn('[BrainDiff] fetch', url, 'error:', err.message);
      }
    }
    return null;
  })();
  return _brainMeshPromise;
}
function buildRealMeshGeometry(payload, targetRadius){
  const flatCoord = (c) => Array.isArray(c[0]) ? c.flat() : c;
  const lh = Float32Array.from(flatCoord(payload.lh_coord));
  const rh = Float32Array.from(flatCoord(payload.rh_coord));
  const lhVerts = lh.length / 3;
  const positions = new Float32Array(lh.length + rh.length);
  positions.set(lh, 0);
  positions.set(rh, lh.length);

  const lhF = flatCoord(payload.lh_faces);
  const rhF = flatCoord(payload.rh_faces);
  const idx = new Uint32Array(lhF.length + rhF.length);
  idx.set(lhF, 0);
  for (let i = 0; i < rhF.length; i++) idx[lhF.length + i] = rhF[i] + lhVerts;

  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();

  // Center + scale so it sits in the same view space as the placeholder sphere.
  g.computeBoundingSphere();
  const bs = g.boundingSphere;
  if (bs){
    const p = g.attributes.position;
    const s = (targetRadius || 1.4) / Math.max(bs.radius, 1e-6);
    const cx = bs.center.x, cy = bs.center.y, cz = bs.center.z;
    for (let i = 0; i < p.count; i++){
      p.setXYZ(i, (p.getX(i) - cx) * s, (p.getY(i) - cy) * s, (p.getZ(i) - cz) * s);
    }
    p.needsUpdate = true;
    g.computeVertexNormals();
    g.computeBoundingSphere();
  }
  return g;
}

function mountBrain(canvas, opts={}){
  const {
    rotation=true,
    rotationSpeed=0.18,
    diff=false,
    highlight=null,
    dpr=Math.min(window.devicePixelRatio||1, 2),
    useRealMesh=false,
    cycleRegions=false,
    diffRegions=null,   // { regionKey: signedDelta } for the compare section
    lensMode=false,     // manual region switching via setHighlight (lens panel)
    initialRegion='attention_salience',
  } = opts;

  // Set inside the real-mesh-ready callback; used by ctrl.setHighlight below.
  let lensSetRegion = null;
  // Each paint mode (cycle / lens / diff) installs a repainter so the brain
  // can re-color itself when the theme flips.
  let themeRepainter = null;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  const renderer = new THREE.WebGLRenderer({canvas, antialias:true, alpha:true});
  renderer.setPixelRatio(dpr);

  // Two brain palettes, one per theme. In dark mode the brain is cream on
  // black with blue highlights; in light mode it inverts — dark slate brain
  // on cream stage with deep blue highlights. applyBrainTheme() re-colors
  // everything when the user toggles the theme.
  const BRAIN_THEMES = {
    dark: {
      base:[0.83, 0.80, 0.73],
      ambient:0xd6d4cc, ambI:0.45,
      key:0xfffaf2,     keyI:1.05,
      fill:0xc2cbd8,    fillI:0.50,
      rim:0x3a4d6b,     rimI:0.40,
    },
    light: {
      // Medium warm gray brain on cream stage — reads like a specimen
      // photograph. Warm undertone so it doesn't clash with the cream page.
      base:[0.56, 0.52, 0.47],
      ambient:0xd8cebd, ambI:0.45,     // warm cream ambient
      key:0xffffff,     keyI:1.20,     // clean white key
      fill:0xf0e2c8,    fillI:0.45,    // warm cream fill
      rim:0x3a4a5c,     rimI:0.55,     // cool blue rim for silhouette separation
    },
  };
  function currentTheme(){
    return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }

  const ambLight = new THREE.AmbientLight(0xffffff, 0.3);
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.0);
  const fillLight = new THREE.DirectionalLight(0xffffff, 0.5);
  const rimLight = new THREE.DirectionalLight(0xffffff, 0.4);
  keyLight.position.set(5, 9, 7);
  fillLight.position.set(-4, 2, 6);
  rimLight.position.set(-6, -2, -8);
  scene.add(ambLight);
  scene.add(keyLight);
  scene.add(fillLight);
  scene.add(rimLight);

  // Sphere-preview canvases (compare/lens placeholders) keep the original
  // neutral lights; the theme-responsive setup below is only for the real
  // cortex renders. Flip a switch so we can dispatch accordingly.
  function applyBrainLighting(theme){
    if (!useRealMesh){
      ambLight.color.setHex(0xe0dccf); ambLight.intensity = 0.32;
      keyLight.color.setHex(0xffffff); keyLight.intensity = 1.05;
      fillLight.color.setHex(0xaec3dc); fillLight.intensity = 0.50;
      rimLight.color.setHex(0x4a78ab); rimLight.intensity = 0.55;
      return;
    }
    const t = BRAIN_THEMES[theme] || BRAIN_THEMES.dark;
    ambLight.color.setHex(t.ambient); ambLight.intensity = t.ambI;
    keyLight.color.setHex(t.key);     keyLight.intensity = t.keyI;
    fillLight.color.setHex(t.fill);   fillLight.intensity = t.fillI;
    rimLight.color.setHex(t.rim);     rimLight.intensity = t.rimI;
  }
  applyBrainLighting(currentTheme());

  const geom = new THREE.SphereGeometry(1, 96, 72);
  const pos = geom.attributes.position;
  for(let i=0;i<pos.count;i++){
    const x=pos.getX(i),y=pos.getY(i),z=pos.getZ(i);
    const bump = 0.06*Math.sin(6*x)*Math.cos(4*y) + 0.04*Math.sin(5*z+1.1);
    const len=Math.sqrt(x*x+y*y+z*z);
    pos.setXYZ(i, x*(1+bump/len), y*(1+bump*0.6/len), z*(1+bump/len));
  }
  geom.computeVertexNormals();

  // Base tone starts from the current theme's palette and swaps when the
  // user toggles dark/light. `let` so applyBrainTheme can update in place.
  const count = pos.count;
  const colors = new Float32Array(count*3);
  let baseR, baseG, baseB;
  (function initBase(){
    const t = useRealMesh ? (BRAIN_THEMES[currentTheme()] || BRAIN_THEMES.dark).base : [0.48, 0.50, 0.55];
    baseR = t[0]; baseG = t[1]; baseB = t[2];
  })();

  // Encoding palette (NEVER change without updating scale-bar gradient)
  const B_R = 0.88, B_G = 0.29, B_B = 0.18;  // vermillion #e04a2e
  const A_R = 0.31, A_G = 0.49, A_B = 0.74;  // slate blue #4f7eb9

  function mixV(a,b,t){return a+(b-a)*t}

  function paint(mode, key){
    for(let i=0;i<count;i++){
      const x=pos.getX(i),y=pos.getY(i),z=pos.getZ(i);
      let r=baseR,g=baseG,b=baseB;
      if(mode==='diff'){
        const t = 0.7*x + 0.4*y - 0.3*z;
        if(t>0){ const u=Math.min(t/0.9,1)**1.3; r=mixV(baseR,B_R,u); g=mixV(baseG,B_G,u); b=mixV(baseB,B_B,u); }
        else { const u=Math.min(-t/0.9,1)**1.3; r=mixV(baseR,A_R,u); g=mixV(baseG,A_G,u); b=mixV(baseB,A_B,u); }
      } else if(mode==='highlight' && key){
        const region = REGIONS[key];
        if(region){
          const d = region.dir;
          const dot = x*d.x + y*d.y + z*d.z;
          if(dot > region.threshold){
            const u = Math.min((dot-region.threshold)/0.25, 1);
            r=mixV(baseR,B_R,u); g=mixV(baseG,B_G,u); b=mixV(baseB,B_B,u);
          }
        }
      }
      colors[i*3]=r; colors[i*3+1]=g; colors[i*3+2]=b;
    }
    geom.setAttribute('color', new THREE.BufferAttribute(colors,3));
    geom.attributes.color.needsUpdate = true;
  }

  const REGIONS = {
    personal_resonance:{dir:new THREE.Vector3(0.2,0.5,0.84).normalize(), threshold:0.35},
    social_thinking:{dir:new THREE.Vector3(-0.9,-0.1,0.3).normalize(), threshold:0.3},
    brain_effort:{dir:new THREE.Vector3(0.85,0.4,0.1).normalize(), threshold:0.25},
    language_depth:{dir:new THREE.Vector3(-0.9,0.0,-0.2).normalize(), threshold:0.28},
    gut_reaction:{dir:new THREE.Vector3(0.0,-0.5,0.8).normalize(), threshold:0.3},
    memory_encoding:{dir:new THREE.Vector3(-0.75,0.25,0.5).normalize(), threshold:0.28},
    attention_salience:{dir:new THREE.Vector3(0.15,0.85,0.2).normalize(), threshold:0.3},
  };

  const material = new THREE.MeshPhysicalMaterial({
    color: 0xffffff,
    vertexColors: true,
    metalness: 0.08,
    roughness: 0.56,
    clearcoat: 0.25,
    clearcoatRoughness: 0.55,
    reflectivity: 0.4,
    sheen: 0.22,
    sheenColor: new THREE.Color(0xcad3df),
    sheenRoughness: 0.66,
    emissive: 0x0a0e14,
    emissiveIntensity: 0.2,
  });

  const root = new THREE.Group();
  const rightGeom = geom.clone();  // keep reference so we can dispose on swap
  const leftHemi = new THREE.Mesh(geom, material);
  leftHemi.scale.set(0.9, 1.25, 1.05);
  leftHemi.position.set(-0.48, 0, 0);
  const rightHemi = new THREE.Mesh(rightGeom, material);
  rightHemi.scale.set(0.9, 1.25, 1.05);
  rightHemi.position.set(0.48, 0, 0);
  root.add(leftHemi, rightHemi);
  scene.add(root);

  paint(diff ? 'diff' : (highlight ? 'highlight' : 'plain'), highlight);

  // Card is now a top strip (not a floating overlay), so the brain doesn't
  // need to be tiny to avoid it. Pull back just enough to leave room for the
  // strip on top + the pills/caption at bottom.
  camera.position.set(0, 0, useRealMesh ? 6.0 : 4.6);
  camera.lookAt(0,0,0);

  // Region-orientation tween targets. The tick loop eases currentRot toward
  // these and adds a small sine sway on top, so transitions between regions
  // feel like the brain calmly turns to show the new area.
  let targetRotY = -0.05, targetRotX = -0.28;
  let currentRotY = -0.05, currentRotX = -0.28;

  // 3D centroid of the currently-active region. The line endpoint projects
  // this through the camera each frame so the line stays anchored to the
  // glowing patch as the brain rotates.
  let activeCentroid = null;

  // Mouse-drag rotation state. When the user drags the canvas, we override
  // the idle sway + region tween with their input. On release, the next pill
  // hover or auto-cycle will gently pull the brain back to a region orient.
  let isDragging = false;
  let dragPointerId = null;
  let dragStartX = 0, dragStartY = 0;
  let dragStartRotY = 0, dragStartRotX = 0;
  if (useRealMesh){
    canvas.style.cursor = 'grab';
    canvas.style.touchAction = 'none';
    canvas.addEventListener('pointerdown', (e) => {
      isDragging = true;
      dragPointerId = e.pointerId;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      dragStartRotY = currentRotY;
      dragStartRotX = currentRotX;
      canvas.setPointerCapture(e.pointerId);
      canvas.style.cursor = 'grabbing';
    });
    canvas.addEventListener('pointermove', (e) => {
      if (!isDragging || e.pointerId !== dragPointerId) return;
      const dx = e.clientX - dragStartX;
      const dy = e.clientY - dragStartY;
      currentRotY = dragStartRotY + dx * 0.008;
      currentRotX = dragStartRotX + dy * 0.008;
      // Collapse the lerp target to where the user is dragging so the tick
      // doesn't snap back while the mouse is held down.
      targetRotY = currentRotY;
      targetRotX = currentRotX;
    });
    const endDrag = (e) => {
      if (!isDragging) return;
      if (e.pointerId !== undefined && e.pointerId !== dragPointerId) return;
      isDragging = false;
      dragPointerId = null;
      canvas.style.cursor = 'grab';
      try { canvas.releasePointerCapture(e.pointerId); } catch(_){}
    };
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
    canvas.addEventListener('pointerleave', endDrag);
  }
  const _projVec = new THREE.Vector3();
  function updateConnectorLine(){
    const lineSvg  = document.getElementById('heroLineSvg');
    const linePath = document.getElementById('heroLinePath');
    const lineEnd  = document.getElementById('heroLineEnd');
    const cardEl   = document.getElementById('heroDimCard');
    if (!lineSvg || !linePath || !lineEnd || !cardEl || !activeCentroid) return;
    root.updateMatrixWorld();
    _projVec.copy(activeCentroid).applyMatrix4(root.matrixWorld).project(camera);
    if (_projVec.z >= 1){
      // behind camera — hide line
      linePath.setAttribute('opacity', '0');
      lineEnd.setAttribute('opacity', '0');
      return;
    }
    linePath.setAttribute('opacity', '1');
    lineEnd.setAttribute('opacity', '1');
    const stageRect = lineSvg.getBoundingClientRect();
    const cardRect  = cardEl.getBoundingClientRect();
    const w = stageRect.width, h = stageRect.height;
    const ex = (_projVec.x + 1) * 0.5 * w;
    const ey = (1 - _projVec.y) * 0.5 * h;
    // Anchor point: bottom-right inset of the card.
    const sx = (cardRect.right - stageRect.left) - 14;
    const sy = (cardRect.bottom - stageRect.top) - 10;
    // Quadratic curve: control point above the midpoint for a gentle arc.
    const mx = (sx + ex) / 2;
    const my = Math.min(sy, ey) - 28;
    linePath.setAttribute('d', `M${sx.toFixed(1)} ${sy.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${ex.toFixed(1)} ${ey.toFixed(1)}`);
    lineEnd.setAttribute('cx', ex.toFixed(1));
    lineEnd.setAttribute('cy', ey.toFixed(1));
  }

  /* ---------------------------------------------------------------
     Region highlighting — used by the hero brain to pulse Attention
     and Memory-encoding areas in sequence, synchronised with the
     annotation card. Works on the real fsaverage5 geometry.
  ----------------------------------------------------------------*/
  // Rough gaussian centres for each of the seven cortical systems, in the
  // post-scaling coord space (mesh normalised to radius ~1.4, centred at 0).
  // Mesh axes: +X = right, +Y = anterior, +Z = superior.
  // These are approximations — enough to light up the right neighbourhood
  // on the cortex without needing the real atlas parcellation client-side.
  const REGION_TARGETS = {
    attention_salience:  [{x:-0.55, y:-0.25, z: 0.85}, {x: 0.55, y:-0.25, z: 0.85}], // bilateral superior parietal + FEF
    memory_encoding:     [{x:-0.95, y: 0.55, z: 0.10}],                               // left vlPFC
    personal_resonance:  [{x: 0.00, y: 0.95, z: 0.30}],                               // medial prefrontal (midline)
    gut_reaction:        [{x:-0.70, y: 0.25, z:-0.05}, {x: 0.70, y: 0.25, z:-0.05}], // bilateral anterior insula
    social_thinking:     [{x:-1.10, y:-0.30, z: 0.45}, {x: 1.10, y:-0.30, z: 0.45}], // bilateral TPJ
    language_depth:      [{x:-1.00, y: 0.55, z: 0.05}, {x:-1.00, y:-0.40, z: 0.15}], // left Broca + Wernicke
    brain_effort:        [{x:-0.85, y: 0.70, z: 0.70}, {x: 0.85, y: 0.70, z: 0.70}], // bilateral dlPFC
  };

  function computeRegionWeights(geometry){
    const p = geometry.attributes.position;
    const n = p.count;
    const sigma2 = 0.32;
    const out = {};
    const centroids = {};
    for (const key of Object.keys(REGION_TARGETS)){
      const targets = REGION_TARGETS[key];
      const w = new Float32Array(n);
      let cx = 0, cy = 0, cz = 0, cw = 0;
      for (let i = 0; i < n; i++){
        const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
        let best = 0;
        for (let t = 0; t < targets.length; t++){
          const tg = targets[t];
          const d2 = (x-tg.x)*(x-tg.x) + (y-tg.y)*(y-tg.y) + (z-tg.z)*(z-tg.z);
          const g = Math.exp(-d2 / sigma2);
          if (g > best) best = g;
        }
        w[i] = best;
        if (best > 0.4){ cx += x*best; cy += y*best; cz += z*best; cw += best; }
      }
      out[key] = w;
      centroids[key] = cw > 0
        ? new THREE.Vector3(cx/cw, cy/cw, cz/cw)
        // Fallback: use the first target centre.
        : new THREE.Vector3(targets[0].x, targets[0].y, targets[0].z);
    }
    out.__centroids = centroids;
    return out;
  }

  const REGION_COPY = {
    attention_salience: {
      label: 'Attention',
      region: 'Dorsal attention network',
      body: "Where the reader locks focus. This network lights up when something breaks the rhythm of what came before — novelty, urgency, a sharp cut, a personal stake.",
      use:  "Super Bowl ad testing · Nielsen / Neuro-Insight · $8M per airing"
    },
    memory_encoding: {
      label: 'Memory encoding',
      region: 'Left ventrolateral prefrontal cortex',
      body: "Not what the reader feels now — what they will still remember tomorrow. Two pieces of content can feel equal in the moment and differ sharply in what sticks.",
      use:  "Mars, Mondelez, Coca-Cola · long-term campaign ROI (sales 6 months out)"
    },
    personal_resonance: {
      label: 'Personal relevance',
      region: 'Medial prefrontal cortex (mPFC)',
      body: "Tracks whether a message feels like it is about you. Activation here has predicted real-world behaviour change where self-reports missed it entirely.",
      use:  "Anti-smoking PSA testing · Falk et al. showed mPFC predicts population quit rates"
    },
    gut_reaction: {
      label: 'Gut reaction',
      region: 'Anterior insula',
      body: "The visceral, felt edge of a message. Sensitive to urgency, moral weight, personal risk — the reaction that arrives before language catches up.",
      use:  "Public-health fear appeals (WHO) · insurance (Allstate \"Mayhem\")"
    },
    social_thinking: {
      label: 'Social reasoning',
      region: 'Temporoparietal junction (TPJ)',
      body: "The cortical system for modelling other minds — figuring out intent, relationship, what a character is about to do.",
      use:  "Netflix thumbnail + trailer testing · which shot makes viewers infer intent"
    },
    language_depth: {
      label: 'Language depth',
      region: "Broca's + Wernicke's network",
      body: "Structural and semantic parsing. Stronger activation means more meaning is being pulled out of the words themselves.",
      use:  "Pharma consent-form comprehension · legal-disclosure testing"
    },
    brain_effort: {
      label: 'Processing effort',
      region: 'Dorsolateral prefrontal cortex (dlPFC)',
      body: "How hard the brain is working to parse the message. Higher effort is fine when the payoff is big — and costly when the reader can just leave.",
      use:  "CFPB mortgage-form simplification · financial disclosure UX"
    },
  };

  // Per-region camera orientation. Brain rotates so the highlighted patch
  // sits roughly in the middle of the stage. Values tuned to center each
  // region based on its anatomical location; larger yaws for lateral/left
  // regions, forward pitch for medial anterior regions.
  const REGION_ORIENT = {
    attention_salience: { y:  0.00, x: -0.25 }, // bilateral dorsal — top-down
    memory_encoding:    { y:  1.05, x:  0.00 }, // left vlPFC — rotate to left 3/4 view
    personal_resonance: { y:  0.00, x: -0.60 }, // mPFC midline — tilt forward to show anterior
    gut_reaction:       { y:  0.85, x:  0.15 }, // bilateral insula — lateral with forward tilt
    social_thinking:    { y:  1.00, x: -0.10 }, // bilateral TPJ — left 3/4 lateral-posterior
    language_depth:     { y:  1.30, x:  0.00 }, // left Broca+Wernicke — left profile view
    brain_effort:       { y:  0.40, x: -0.30 }, // bilateral dlPFC — slight left dorsolateral
  };

  // Activation gradient LUT. Two calibrations:
  //   - CREAM base (dark theme): cream → periwinkle → royal → deep blue.
  //     The intermediate stops brighten slightly before darkening, giving a
  //     "soft paper absorbing ink" feel that reads well on a near-black stage.
  //   - WARM-GRAY base (light theme): gray → slate → royal → deep navy.
  //     Monotonic cooling + darkening — no lightening bump — so activation
  //     reads as "more intense = darker blue" against the cream stage.
  const LUT_SIZE = 128;
  function buildHeatLUT(baseDim){
    const lut = new Float32Array(LUT_SIZE * 3);
    const dimR = baseDim[0], dimG = baseDim[1], dimB = baseDim[2];
    const isCream = (dimR + dimG + dimB) / 3 > 0.65;
    function lerp(a,b,u){ return a + (b-a)*u; }
    // Stops: [tStart, tEnd, rFrom, gFrom, bFrom, rTo, gTo, bTo]
    const stops = isCream ? [
      [0.00, 0.25, dimR, dimG, dimB,  0.72, 0.74, 0.82],   // cream → faint blue
      [0.25, 0.55, 0.72, 0.74, 0.82,  0.50, 0.60, 0.86],   // faint blue → periwinkle
      [0.55, 0.78, 0.50, 0.60, 0.86,  0.22, 0.38, 0.78],   // periwinkle → royal
      [0.78, 1.00, 0.22, 0.38, 0.78,  0.06, 0.18, 0.62],   // royal → deep blue
    ] : [
      [0.00, 0.30, dimR, dimG, dimB,  0.42, 0.45, 0.55],   // warm gray → cool gray
      [0.30, 0.60, 0.42, 0.45, 0.55,  0.26, 0.36, 0.58],   // cool gray → slate blue
      [0.60, 0.82, 0.26, 0.36, 0.58,  0.13, 0.26, 0.56],   // slate → royal
      [0.82, 1.00, 0.13, 0.26, 0.56,  0.04, 0.14, 0.50],   // royal → deep navy
    ];
    for (let i = 0; i < LUT_SIZE; i++){
      const t = i / (LUT_SIZE - 1);
      let r = dimR, g = dimG, b = dimB;
      for (let s = 0; s < stops.length; s++){
        const st = stops[s];
        if (t >= st[0] && t <= st[1]){
          const u = (t - st[0]) / (st[1] - st[0]);
          r = lerp(st[2], st[5], u);
          g = lerp(st[3], st[6], u);
          b = lerp(st[4], st[7], u);
          break;
        }
      }
      lut[i*3] = r; lut[i*3+1] = g; lut[i*3+2] = b;
    }
    return lut;
  }

  // Lens mode — single region at a time, manual switching via setHighlight.
  // No auto-cycle, no pill listeners (the lens panel owns its own pills).
  // Returns a setHighlight(key) function that paints the region and eases
  // the brain toward that region's orientation.
  function startLensMode(geometry, colors, nVerts, initialKey){
    const weights = computeRegionWeights(geometry);
    const LUT_MAX = LUT_SIZE - 1;
    let currentKey = initialKey;
    let currentLUT = buildHeatLUT([baseR, baseG, baseB]);

    function paintRegion(key){
      const w = weights[key];
      if (!w) return;
      for (let i = 0; i < nVerts; i++){
        const t = w[i];
        const u = Math.min(1, Math.pow(t, 0.9) * 1.15);
        const idx = Math.min(LUT_MAX, Math.floor(u * LUT_MAX));
        colors[i*3]   = currentLUT[idx*3];
        colors[i*3+1] = currentLUT[idx*3+1];
        colors[i*3+2] = currentLUT[idx*3+2];
      }
      geometry.attributes.color.needsUpdate = true;
    }

    function setHighlight(key){
      currentKey = key;
      paintRegion(key);
      const orient = REGION_ORIENT[key];
      if (orient){ targetRotY = orient.y; targetRotX = orient.x; }
      const cents = weights.__centroids;
      if (cents && cents[key]) activeCentroid = cents[key];
    }

    setHighlight(initialKey);
    themeRepainter = () => {
      currentLUT = buildHeatLUT([baseR, baseG, baseB]);
      paintRegion(currentKey);
    };
    return setHighlight;
  }

  // Paints the real mesh with a diverging blue↔vermillion map based on
  // per-region signed deltas (positive = B stronger, negative = A stronger).
  // Mock data now — swap in real backend deltas later without code changes.
  function paintMockDiff(geometry, colors, nVerts, regionDeltas){
    const regionWeights = computeRegionWeights(geometry);
    // Accumulate a signed per-vertex delta: Σ weight[region][i] * delta[region]
    const dPerVert = new Float32Array(nVerts);
    let maxAbs = 0;
    for (const key of Object.keys(regionDeltas)){
      const w = regionWeights[key];
      const d = regionDeltas[key];
      if (!w) continue;
      for (let i = 0; i < nVerts; i++){
        dPerVert[i] += w[i] * d;
      }
    }
    for (let i = 0; i < nVerts; i++) if (Math.abs(dPerVert[i]) > maxAbs) maxAbs = Math.abs(dPerVert[i]);
    const scale = maxAbs > 1e-6 ? 1 / maxAbs : 1;
    const POS  = [0.92, 0.32, 0.20];
    const NEG  = [0.32, 0.54, 0.80];
    function repaint(){
      const NEUT = [baseR, baseG, baseB];
      for (let i = 0; i < nVerts; i++){
        const d = dPerVert[i] * scale;
        const u = Math.min(1, Math.abs(d));
        const target = d >= 0 ? POS : NEG;
        colors[i*3]   = NEUT[0] + (target[0] - NEUT[0]) * u;
        colors[i*3+1] = NEUT[1] + (target[1] - NEUT[1]) * u;
        colors[i*3+2] = NEUT[2] + (target[2] - NEUT[2]) * u;
      }
      geometry.attributes.color.needsUpdate = true;
    }
    repaint();
    themeRepainter = repaint;
  }

  function startRegionCycle(geometry, colors, nVerts){
    const weights = computeRegionWeights(geometry);
    // Base is now dark on its own — no extra dim multiplier needed. The LUT
    // starts from the full base colour, so unilluminated cortex shows its
    // real shaded slate tone with all the gyri and sulci visible.
    const DIM = 1.0;
    let heatLUT = buildHeatLUT([baseR * DIM, baseG * DIM, baseB * DIM]);

    // Crossfade between two weight buffers using the heat LUT.
    const displayW = new Float32Array(nVerts);
    function paintFromBlended(fromW, toW, e){
      const last = LUT_SIZE - 1;
      for (let i = 0; i < nVerts; i++){
        const t = fromW[i] * (1 - e) + toW[i] * e;
        const tFloor = 0.24;
        const tAdj = tFloor + (1 - tFloor) * (t < 0 ? 0 : t > 1 ? 1 : t);
        const idx = (tAdj * last) | 0;
        const li = idx * 3;
        colors[i*3  ] = heatLUT[li];
        colors[i*3+1] = heatLUT[li+1];
        colors[i*3+2] = heatLUT[li+2];
      }
      geometry.attributes.color.needsUpdate = true;
    }
    function paintFromWeight(w){
      paintFromBlended(w, w, 0); // identical from/to → just paint w
      // also stash as the current display buffer
      displayW.set(w);
    }

    // Cubic-ease crossfade scheduler.
    let xfFrom = null, xfTo = null, xfStart = 0;
    const XF_MS = 700;
    function startCrossfade(toW){
      // From = current display, so transitions chain cleanly even mid-fade.
      xfFrom = new Float32Array(displayW);
      xfTo = toW;
      xfStart = performance.now();
      const tick = () => {
        const f = Math.min(1, (performance.now() - xfStart) / XF_MS);
        const e = f < 0.5 ? 4*f*f*f : 1 - Math.pow(-2*f + 2, 3) / 2;
        paintFromBlended(xfFrom, xfTo, e);
        // also advance displayW so subsequent crossfades start from "now"
        for (let i = 0; i < nVerts; i++){
          displayW[i] = xfFrom[i] * (1 - e) + xfTo[i] * e;
        }
        if (f < 1) requestAnimationFrame(tick);
        else { xfFrom = null; xfTo = null; }
      };
      requestAnimationFrame(tick);
    }

    const card   = document.getElementById('heroDimCard');
    const useLn  = document.getElementById('heroUseLine');
    const nmEl   = document.getElementById('heroDimLabel');
    const rgEl   = document.getElementById('heroDimRegion');
    const bdEl   = document.getElementById('heroDimBody');
    const useEl  = document.getElementById('heroUseText');
    const pillsEl = document.getElementById('heroPills');

    function updatePillActive(key){
      if (!pillsEl) return;
      pillsEl.querySelectorAll('.hero-pill').forEach(p => {
        p.classList.toggle('is-active', p.dataset.key === key);
      });
    }

    function swapCopy(key){
      const c = REGION_COPY[key];
      if (!c) return;
      if (card)  card.classList.add('fading');
      if (useLn) useLn.classList.add('fading');
      setTimeout(() => {
        if (nmEl)  nmEl.textContent  = c.label;
        if (rgEl)  rgEl.textContent  = c.region;
        if (bdEl)  bdEl.textContent  = c.body;
        if (useEl) useEl.textContent = c.use;
        if (card)  card.classList.remove('fading');
        if (useLn) useLn.classList.remove('fading');
      }, 280);
    }

    function go(key){
      const w = weights[key];
      if (!w) return;
      // Aim the camera toward this region's view.
      const orient = REGION_ORIENT[key];
      if (orient){ targetRotY = orient.y; targetRotX = orient.x; }
      // Update connector line endpoint.
      const cents = weights.__centroids;
      if (cents && cents[key]) activeCentroid = cents[key];
      // Smooth colour crossfade.
      startCrossfade(w);
      // Card + pill state in parallel.
      swapCopy(key);
      updatePillActive(key);
    }

    // Auto-cycle between the two flagship dimensions.
    const autoOrder = ['attention_salience', 'memory_encoding'];
    let autoIdx = 0;
    let autoTimer = null;
    const INTERVAL_MS = 8000;

    function startAuto(){
      if (autoTimer) return;
      autoTimer = setInterval(() => {
        autoIdx = (autoIdx + 1) % autoOrder.length;
        go(autoOrder[autoIdx]);
      }, INTERVAL_MS);
    }
    function stopAuto(){
      if (autoTimer){ clearInterval(autoTimer); autoTimer = null; }
    }

    // ----- Pill hover + Others popover (JS-controlled, not CSS-only) -----
    // Debounced resume so the user can move between pills and into the
    // popover without restarting the auto-cycle.
    let resumeTimer = null;
    function scheduleResume(){
      if (resumeTimer) clearTimeout(resumeTimer);
      resumeTimer = setTimeout(() => {
        autoIdx = 0;                  // reset to Attention
        go(autoOrder[autoIdx]);
        startAuto();
        resumeTimer = null;
      }, 320);
    }
    function cancelResume(){
      if (resumeTimer){ clearTimeout(resumeTimer); resumeTimer = null; }
    }

    const pillGroup = pillsEl ? pillsEl.querySelector('.hero-pill-group') : null;
    let popoverCloseTimer = null;
    function openPopover(){
      if (popoverCloseTimer){ clearTimeout(popoverCloseTimer); popoverCloseTimer = null; }
      if (pillGroup) pillGroup.classList.add('is-open');
    }
    function closePopover(immediate){
      if (popoverCloseTimer){ clearTimeout(popoverCloseTimer); popoverCloseTimer = null; }
      if (immediate){
        if (pillGroup) pillGroup.classList.remove('is-open');
      } else {
        popoverCloseTimer = setTimeout(() => {
          if (pillGroup) pillGroup.classList.remove('is-open');
          popoverCloseTimer = null;
        }, 180);
      }
    }
    if (pillGroup){
      pillGroup.addEventListener('mouseenter', openPopover);
      pillGroup.addEventListener('mouseleave', () => closePopover(false));
      pillGroup.addEventListener('focusin', openPopover);
      pillGroup.addEventListener('focusout', () => {
        setTimeout(() => {
          if (!pillGroup.contains(document.activeElement)) closePopover(true);
        }, 50);
      });
    }

    if (pillsEl){
      pillsEl.querySelectorAll('.hero-pill[data-key]').forEach(pill => {
        const key = pill.dataset.key;
        const isInPopover = !!pill.closest('.hero-pill-popover');
        const activate = () => { cancelResume(); stopAuto(); go(key); };
        pill.addEventListener('mouseenter', () => {
          activate();
          // Hovering Attention/Memory (outside popover) should close the
          // Others popover immediately so it doesn't linger.
          if (!isInPopover) closePopover(true);
        });
        pill.addEventListener('focus', activate);
        // Click is treated as activate ONLY — no blur, no popover close, no
        // resume schedule. This prevents the "click on Processing Effort →
        // brain rotates there → 320ms later auto-resumes to Attention" bounce.
        pill.addEventListener('click', activate);
        pill.addEventListener('mouseleave', scheduleResume);
      });
    }

    // First paint — set displayW to the initial region weights without a
    // visible transition (skip the crossfade so the brain renders correctly
    // right after the sphere fades out).
    paintFromWeight(weights[autoOrder[autoIdx]]);
    swapCopy(autoOrder[autoIdx]);
    updatePillActive(autoOrder[autoIdx]);
    const orient0 = REGION_ORIENT[autoOrder[autoIdx]];
    if (orient0){ targetRotY = orient0.y; targetRotX = orient0.x; }
    startAuto();

    // On theme toggle, rebuild the LUT with the new base colour and repaint
    // the currently-displayed region. The sway + rotation continue as usual.
    themeRepainter = () => {
      heatLUT = buildHeatLUT([baseR * DIM, baseG * DIM, baseB * DIM]);
      paintFromBlended(displayW, displayW, 0);
    };
  }

  /* ---------------------------------------------------------------
     Real fsaverage5 mesh swap-in (optional).
     Flow: placeholder sphere renders immediately → fetch /api/brain-mesh
     in background → on arrival, crossfade sphere out + real mesh in.
     Silent fallback to the sphere if the backend is unreachable.
  ----------------------------------------------------------------*/
  if (useRealMesh) {
    fetchBrainMesh().then((payload) => {
      if (!payload) {
        console.warn('[BrainDiff] /api/brain-mesh unavailable — keeping placeholder cortex.');
        return;
      }
      try {
        const realGeom = buildRealMeshGeometry(payload, 1.4);
        // Neutral base color for the real cortex (matches the pewter placeholder tone).
        const nVerts = realGeom.attributes.position.count;
        const realColors = new Float32Array(nVerts * 3);
        for (let i = 0; i < nVerts; i++) {
          realColors[i*3]   = baseR;
          realColors[i*3+1] = baseG;
          realColors[i*3+2] = baseB;
        }
        realGeom.setAttribute('color', new THREE.BufferAttribute(realColors, 3));

        const realMat = new THREE.MeshPhysicalMaterial({
          color: 0xffffff,
          vertexColors: true,
          metalness: 0.08,
          roughness: 0.56,
          clearcoat: 0.25,
          clearcoatRoughness: 0.55,
          reflectivity: 0.4,
          sheen: 0.22,
          sheenColor: new THREE.Color(0xcad3df),
          sheenRoughness: 0.66,
          emissive: 0x0a0e14,
          emissiveIntensity: 0.2,
          transparent: true,
          opacity: 0,
        });
        const realMesh = new THREE.Mesh(realGeom, realMat);
        // fsaverage5 from nilearn arrives in RAS-like orientation:
        //   +X = right · +Y = anterior · +Z = superior
        // With the camera at (0,0,4.6) looking down -Z, leaving rotations at
        // zero gives a true dorsal view (looking at the top of the head with
        // anterior up, right hemisphere on the right). The gentle sway is
        // driven by root.rotation in the tick loop, not by the mesh itself.
        realMesh.rotation.set(0, 0, 0);
        root.add(realMesh);

        // Crossfade: 900ms
        material.transparent = true;
        const fadeMs = 900;
        const startTs = performance.now();
        (function fadeStep(){
          const e = Math.min(1, (performance.now() - startTs) / fadeMs);
          material.opacity = 1 - e;
          realMat.opacity = e;
          if (e < 1) requestAnimationFrame(fadeStep);
          else {
            // Dispose the placeholder once it's offscreen.
            root.remove(leftHemi);
            root.remove(rightHemi);
            geom.dispose();
            rightGeom.dispose();
            material.dispose();
            if (cycleRegions) startRegionCycle(realGeom, realColors, nVerts);
            else if (diffRegions) paintMockDiff(realGeom, realColors, nVerts, diffRegions);
            else if (lensMode) lensSetRegion = startLensMode(realGeom, realColors, nVerts, initialRegion);
          }
        })();
      } catch (err) {
        console.warn('[BrainDiff] failed to build real mesh geometry:', err);
      }
    });
  }

  function resize(){
    const r = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(r.width));
    const h = Math.max(1, Math.floor(r.height));
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(canvas.parentElement);

  const t0 = performance.now();
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let raf = 0;
  function tick(now){
    raf = requestAnimationFrame(tick);
    const t = (now - t0) * 0.001;
    if(rotation && !reduced){
      if (useRealMesh){
        if (isDragging){
          // Direct user control — skip sway + lerp so cursor maps 1:1.
          root.rotation.y = currentRotY;
          root.rotation.x = currentRotX;
        } else {
          // Ease toward the active region's orientation. 0.045 lerp lands in
          // ~700ms — slow enough to read as a deliberate camera move.
          currentRotY += (targetRotY - currentRotY) * 0.045;
          currentRotX += (targetRotX - currentRotX) * 0.045;
          root.rotation.y = currentRotY + Math.sin(t * 0.18) * 0.06;
          root.rotation.x = currentRotX + Math.sin(t * 0.14 + 0.6) * 0.025;
        }
      } else {
        // Placeholder sphere (compare / lens canvases) — original motion.
        root.rotation.y = -0.42 + Math.sin(t*rotationSpeed)*0.08 + t*0.12;
        root.rotation.x = -0.05 + Math.sin(t*rotationSpeed*0.8+0.9)*0.04;
      }
    }
    renderer.render(scene, camera);
    if (useRealMesh) updateConnectorLine();
  }
  raf = requestAnimationFrame(tick);

  // Listen for theme toggles and recolour everything — base, lighting, LUT —
  // so the dark ↔ light transition is coherent across the whole brain scene.
  function onThemeChange(ev){
    const theme = (ev && ev.detail && ev.detail.theme) || currentTheme();
    if (useRealMesh){
      const t = BRAIN_THEMES[theme] || BRAIN_THEMES.dark;
      baseR = t.base[0]; baseG = t.base[1]; baseB = t.base[2];
    }
    applyBrainLighting(theme);
    if (themeRepainter) themeRepainter();
  }
  window.addEventListener('braindiff:theme', onThemeChange);

  return {
    setHighlight(k){
      // Prefer the lens-mode real-mesh highlighter once the real mesh has
      // loaded; fall back to the sphere's region-direction highlight until
      // then (or for non-lens canvases that still use the placeholder).
      if (lensSetRegion) { lensSetRegion(k); return; }
      paint('highlight', k);
    },
    dispose(){
      window.removeEventListener('braindiff:theme', onThemeChange);
      cancelAnimationFrame(raf); ro.disconnect(); renderer.dispose(); geom.dispose(); material.dispose();
    }
  };
}

// ─── Module exports — used by results pages to mount their own brains
export { mountBrain, fetchBrainMesh, buildRealMeshGeometry };
