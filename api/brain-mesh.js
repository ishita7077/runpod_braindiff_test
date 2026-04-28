const { methodNotAllowed } = require("./lib/http");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  // The Vercel adapter does not currently ship the heavy fsaverage mesh payload.
  // Frontend callers already fall back to the procedural placeholder when this returns non-OK.
  res.status(204).end();
};
