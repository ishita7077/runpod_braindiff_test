const { methodNotAllowed } = require("./lib/http");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  // Keep this endpoint non-failing so frontend mesh fetch never emits hard errors.
  // The viewer already handles null by using the procedural placeholder.
  res.setHeader("Cache-Control", "public, max-age=300, s-maxage=300");
  res.status(200).json(null);
};
