/**
 * Export an Excalidraw scene to SVG or PNG using headless Chrome + @excalidraw/utils.
 *
 * Usage: node export.mjs <input.excalidraw> <output.svg|png> [--chrome /path/to/chrome]
 *
 * Uses the pre-built UMD bundle from @excalidraw/utils loaded directly in the
 * browser page. puppeteer-core reuses the system Chrome/Chromium.
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
  console.error("Usage: node export.mjs <input.excalidraw> <output.svg|png> [--chrome /path/to/chrome]");
  process.exit(1);
}

const scene = JSON.parse(readFileSync(resolve(inputPath), "utf-8"));
const isPng = outputPath.endsWith(".png");

// Path to the pre-built UMD bundle
const utilsBundlePath = resolve(
  __dirname, "node_modules", "@excalidraw", "utils", "dist", "excalidraw-utils.min.js",
);

const browser = await puppeteer.launch({
  headless: true,
  executablePath: chromePath || undefined,
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
});

try {
  const page = await browser.newPage();

  // Start with a blank page
  await page.setContent("<!DOCTYPE html><html><head></head><body></body></html>");

  // Load the UMD bundle — exposes ExcalidrawUtils globally
  await page.addScriptTag({ path: utilsBundlePath });

  // Verify it loaded
  const hasUtils = await page.evaluate(() => typeof ExcalidrawUtils !== "undefined");
  if (!hasUtils) {
    throw new Error("@excalidraw/utils UMD bundle did not load correctly");
  }

  // Run the export inside the browser context
  const svgString = await page.evaluate(async (sceneData) => {
    const svg = await ExcalidrawUtils.exportToSvg({
      elements: sceneData.elements || [],
      appState: {
        exportBackground: true,
        viewBackgroundColor: sceneData.appState?.viewBackgroundColor || "#ffffff",
        ...sceneData.appState,
      },
      files: sceneData.files || {},
    });
    return svg.outerHTML;
  }, scene);

  if (isPng) {
    // Render the SVG in the page and screenshot it.
    // Use networkidle0 to wait for external font downloads (Virgil, Cascadia).
    await page.setContent(
      `<!DOCTYPE html><html><body style="margin:0;padding:0;background:transparent">${svgString}</body></html>`,
      { waitUntil: "networkidle0", timeout: 15000 },
    );
    // Wait for fonts to load and render to complete
    await page.evaluate(() => document.fonts.ready);
    // Extra frame to ensure paint
    await new Promise(r => setTimeout(r, 200));

    const svgEl = await page.$("svg");
    if (!svgEl) throw new Error("SVG element not found after render");
    const box = await svgEl.boundingBox();
    const pngBuffer = await svgEl.screenshot({
      type: "png",
      clip: { x: box.x, y: box.y, width: box.width, height: box.height },
    });
    writeFileSync(resolve(outputPath), pngBuffer);
  } else {
    writeFileSync(resolve(outputPath), svgString);
  }
} finally {
  await browser.close();
}
