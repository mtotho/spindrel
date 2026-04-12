/**
 * Convert a Mermaid diagram to Excalidraw JSON using headless Chrome.
 *
 * Usage: node mermaid_convert.mjs <input.mmd> <output.excalidraw> [--chrome /path/to/chrome]
 *
 * Both mermaid and @excalidraw/mermaid-to-excalidraw require a DOM, so we run
 * them inside a headless Chrome page via Puppeteer. Mermaid is loaded as its
 * built-in UMD bundle; mermaid-to-excalidraw is pre-bundled via esbuild.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

const __dirname = dirname(fileURLToPath(import.meta.url));

const args = process.argv.slice(2);
let inputPath, outputPath, chromePath;

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--chrome" && args[i + 1]) {
    chromePath = args[++i];
  } else if (!inputPath) {
    inputPath = args[i];
  } else {
    outputPath = args[i];
  }
}

if (!inputPath || !outputPath) {
  console.error("Usage: node mermaid_convert.mjs <input.mmd> <output.excalidraw> [--chrome /path/to/chrome]");
  process.exit(1);
}

const mermaidSyntax = readFileSync(resolve(inputPath), "utf-8");

// Self-contained bundle (mermaid + mermaid-to-excalidraw, built via esbuild)
const m2eBundle = resolve(__dirname, "mermaid-to-excalidraw.bundle.js");

const browser = await puppeteer.launch({
  headless: true,
  executablePath: chromePath || undefined,
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
});

try {
  const page = await browser.newPage();
  await page.setContent("<!DOCTYPE html><html><head></head><body></body></html>");

  // Load self-contained bundle (mermaid + mermaid-to-excalidraw)
  await page.addScriptTag({ path: m2eBundle });
  await page.waitForFunction(
    () => typeof window.parseMermaidToExcalidraw === "function",
    { timeout: 10000 },
  );

  // Convert
  const result = await page.evaluate(async (syntax) => {
    try {
      if (typeof parseMermaidToExcalidraw !== "function") {
        return { error: "parseMermaidToExcalidraw not available after loading bundle" };
      }
      const { elements, files } = await parseMermaidToExcalidraw(syntax, { fontSize: 16 });
      return { elements: elements || [], files: files || {} };
    } catch (err) {
      return { error: err.message || String(err) };
    }
  }, mermaidSyntax);

  if (result.error) {
    console.error(`Mermaid conversion error: ${result.error}`);
    process.exit(1);
  }

  const scene = {
    type: "excalidraw",
    version: 2,
    source: "spindrel-mermaid",
    elements: result.elements,
    appState: { viewBackgroundColor: "#ffffff" },
    files: result.files,
  };

  writeFileSync(resolve(outputPath), JSON.stringify(scene, null, 2));
} finally {
  await browser.close();
}
