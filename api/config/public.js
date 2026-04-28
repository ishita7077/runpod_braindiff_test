const { methodNotAllowed, serverError } = require("../lib/http");
const { publicShellConfig } = require("../lib/config");

module.exports = async function handler(req, res) {
  if (req.method !== "GET") return methodNotAllowed(res, ["GET"]);
  try {
    const { turnstileSiteKey, turnstileRequired } = publicShellConfig();
    res.status(200).json({ turnstileSiteKey, turnstileRequired });
  } catch (err) {
    serverError(res, err, "PUBLIC_CONFIG_FAILED");
  }
};
