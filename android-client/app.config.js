const fs = require("fs");
const path = require("path");

// Read the server's .env file at build time to preload defaults
// so you don't have to type them on the device.
function loadParentEnv() {
  const envPath = path.resolve(__dirname, "..", ".env");
  const vars = {};
  try {
    const content = fs.readFileSync(envPath, "utf-8");
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq === -1) continue;
      const key = trimmed.slice(0, eq).trim();
      const value = trimmed.slice(eq + 1).trim();
      vars[key] = value;
    }
  } catch {
    // .env not found — that's fine, user configures in-app
  }
  return vars;
}

const env = loadParentEnv();

// Pull the base app.json config
const appJson = require("./app.json");

module.exports = {
  ...appJson.expo,
  extra: {
    apiKey: env.API_KEY || "",
    agentUrl: env.ANDROID_AGENT_URL || "",
    picovoiceAccessKey: env.PICOVOICE_ACCESS_KEY || "",
  },
};
