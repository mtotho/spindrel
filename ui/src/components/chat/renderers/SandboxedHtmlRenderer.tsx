/**
 * Sandboxed HTML envelope renderer.
 *
 * Tools (or pinned files) opting into `text/html` content render through
 * this component. The body is injected into an iframe via `srcdoc` with
 * a strict sandbox attribute and a CSP meta tag — no scripts, no
 * network, no parent access. Bots that get prompt-injected into emitting
 * HTML cannot escape into the host page.
 *
 * Sandbox model:
 * - `sandbox=""` — no allow-* tokens, so the iframe gets the most
 *   restrictive treatment: no scripts, no forms, no popups, no
 *   same-origin, no top-level navigation.
 * - CSP meta tag injected at the top of `srcdoc`: `default-src 'none'`
 *   blocks every fetch (network, CSS @import, fonts, images via http).
 *   `style-src 'unsafe-inline'` allows inline `<style>` so bots can
 *   theme their output. `img-src data: blob:` allows inline images
 *   without enabling network image loads.
 * - Iframe height grows with the content via `auto` after onLoad.
 */
import { useEffect, useRef, useState } from "react";
import type { ThemeTokens } from "../../../theme/tokens";
import type { RichRendererChromeMode } from "./genericRendererChrome";

interface Props {
  body: string;
  chromeMode?: RichRendererChromeMode;
  t: ThemeTokens;
}

const CSP =
  "default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:";

function wrapHtml(body: string): string {
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${CSP}" />
<style>
  html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-size: 13px; color: #333; }
  body { padding: 8px 12px; }
  * { max-width: 100%; }
  img, video { max-width: 100%; height: auto; }
  table { border-collapse: collapse; }
  td, th { padding: 4px 8px; border: 1px solid #ddd; }
</style>
</head>
<body>
${body}
</body>
</html>`;
}

export function SandboxedHtmlRenderer({
  body,
  chromeMode = "standalone",
  t,
}: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(120);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const handler = () => {
      try {
        // Even with sandbox="", we can read contentDocument from the
        // parent because srcdoc gives the parent same-document access
        // for measurement purposes.
        const doc = iframe.contentDocument;
        if (doc?.body) {
          const h = Math.min(doc.body.scrollHeight + 24, 600);
          setHeight(Math.max(60, h));
        }
      } catch {
        // Same-origin access blocked — fall back to default height.
      }
    };
    iframe.addEventListener("load", handler);
    return () => iframe.removeEventListener("load", handler);
  }, [body]);

  return (
    <div
      style={{
        borderRadius: chromeMode === "embedded" ? 0 : 8,
        border: chromeMode === "embedded" ? "none" : `1px solid ${t.surfaceBorder}`,
        overflow: "hidden",
        background: chromeMode === "embedded" ? "transparent" : "#ffffff",
      }}
    >
      <iframe
        ref={iframeRef}
        srcDoc={wrapHtml(body)}
        sandbox=""
        title="Tool result"
        style={{
          width: "100%",
          height,
          border: "none",
          display: "block",
        }}
      />
    </div>
  );
}
