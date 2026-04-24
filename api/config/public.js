const { methodNotAllowed, serverError } = require("../lib/http");
const { runtimeConfig } = require("../lib/config");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  try {
    const cfg = runtimeConfig();
    res.status(200).json({
      turnstileSiteKey: cfg.turnstileSiteKey
    });
  } catch (err) {
    serverError(res, err, "PUBLIC_CONFIG_FAILED");
  }
};
