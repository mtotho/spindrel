/**
 * Plain-text envelope renderer.
 *
 * Default mimetype handler — used when no more specific renderer matches,
 * or when a tool returns text/plain. Monospace, preserve whitespace, soft
 * border to distinguish from chat content.
 */
import type { ThemeTokens } from "../../../theme/tokens";
import type { RichRendererChromeMode, RichRendererVariant } from "./genericRendererChrome";
import { resolveCodeShell } from "./genericRendererChrome";

interface Props {
  body: string;
  rendererVariant?: RichRendererVariant;
  chromeMode?: RichRendererChromeMode;
  t: ThemeTokens;
}

export function TextRenderer({
  body,
  rendererVariant = "default-chat",
  chromeMode = "standalone",
  t,
}: Props) {
  return (
    <pre
      style={{
        ...resolveCodeShell({ t, rendererVariant, chromeMode }),
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {body}
    </pre>
  );
}
