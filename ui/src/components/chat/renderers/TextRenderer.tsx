/**
 * Plain-text envelope renderer.
 *
 * Default mimetype handler — used when no more specific renderer matches,
 * or when a tool returns text/plain. Monospace, preserve whitespace, soft
 * border to distinguish from chat content.
 */
import type { ThemeTokens } from "../../../theme/tokens";

interface Props {
  body: string;
  t: ThemeTokens;
}

export function TextRenderer({ body, t }: Props) {
  return (
    <pre
      style={{
        margin: 0,
        padding: "8px 12px",
        borderRadius: 6,
        background: t.codeBg,
        border: `1px solid ${t.codeBorder}`,
        fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
        fontSize: 12,
        lineHeight: 1.5,
        color: t.contentText,
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        maxHeight: 360,
        overflowY: "auto",
      }}
    >
      {body}
    </pre>
  );
}
