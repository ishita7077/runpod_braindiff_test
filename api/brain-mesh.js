const { methodNotAllowed } = require("./lib/http");

let cachedPayload = null;

function buildHemisphere(side) {
  const latSteps = 38;
  const lonSteps = 56;
  const coord = [];
  const faces = [];

  for (let i = 0; i <= latSteps; i += 1) {
    const v = i / latSteps;
    const theta = -Math.PI / 2 + v * Math.PI;
    for (let j = 0; j <= lonSteps; j += 1) {
      const u = j / lonSteps;
      const phi = u * Math.PI * 2;
      const fold =
        1 +
        0.07 * Math.sin(10 * phi + 2.2 * Math.sin(theta * 2)) +
        0.04 * Math.sin(12 * theta + side * 1.7) +
        0.025 * Math.cos(18 * (u + v));
      let x = side * 0.48 + Math.cos(theta) * Math.cos(phi) * 0.58 * fold;
      if (side * x < 0.1) x = side * (0.1 + 0.035 * Math.sin(theta * 7 + phi * 3));
      const y = Math.sin(theta) * 0.78 * fold;
      const z = Math.cos(theta) * Math.sin(phi) * 1.08 * fold;
      coord.push([round3(x), round3(y), round3(z)]);
    }
  }

  for (let i = 0; i < latSteps; i += 1) {
    for (let j = 0; j < lonSteps; j += 1) {
      const a = i * (lonSteps + 1) + j;
      const b = a + 1;
      const c = a + (lonSteps + 1);
      const d = c + 1;
      if (side > 0) faces.push([a, c, b], [b, c, d]);
      else faces.push([a, b, c], [b, d, c]);
    }
  }

  return { coord, faces };
}

function round3(value) {
  return Math.round(value * 1000) / 1000;
}

function buildPayload() {
  if (cachedPayload) return cachedPayload;
  const lh = buildHemisphere(-1);
  const rh = buildHemisphere(1);
  cachedPayload = {
    format: "procedural_folded_cortex_v1",
    lh_coord: lh.coord,
    lh_faces: lh.faces,
    rh_coord: rh.coord,
    rh_faces: rh.faces
  };
  return cachedPayload;
}

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  res.setHeader("Cache-Control", "public, max-age=3600, s-maxage=86400");
  res.status(200).json(buildPayload());
};
