#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const envPath = path.resolve(__dirname, "..", "..", ".env");
const outPath = path.resolve(__dirname, "..", "src", "env.generated.ts");

const vars = {};
try {
  const content = fs.readFileSync(envPath, "utf-8");
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    vars[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
  }
} catch {
  // no .env — generate empty defaults
}

const ts = `// Auto-generated from ../.env — do not edit manually.
// Regenerate with: npm run env
export const BUILD_API_KEY = ${JSON.stringify(vars.API_KEY || "")};
export const BUILD_AGENT_URL = ${JSON.stringify(vars.ANDROID_AGENT_URL || "")};
export const BUILD_PICOVOICE_KEY = ${JSON.stringify(vars.PICOVOICE_ACCESS_KEY || "")};
`;

fs.writeFileSync(outPath, ts);
console.log("Generated src/env.generated.ts");
