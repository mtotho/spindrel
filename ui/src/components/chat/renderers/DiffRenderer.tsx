/**
 * Unified-diff envelope renderer.
 *
 * Used for `application/vnd.spindrel.diff+text`. Parses lines that start
 * with `+`/`-`/` `/`@@` and renders them with success/danger background
 * tints from the existing theme tokens. The +/− gutter is fixed-width so
 * long lines wrap inside the line's content cell rather than offsetting
 * subsequent lines.
 *
 * Empty diff body → "(no changes)" placeholder.
 */
import type { ThemeTokens } from "../../../theme/tokens";

interface Props {
  body: string;
  t: ThemeTokens;
}

type DiffLine =
  | { kind: "add"; text: string }
  | { kind: "remove"; text: string }
  | { kind: "context"; text: string }
  | { kind: "hunk"; text: string }
  | { kind: "header"; text: string };

function parseDiff(body: string): DiffLine[] {
  const out: DiffLine[] = [];
  for (const line of body.split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) {
      out.push({ kind: "header", text: line });
    } else if (line.startsWith("@@")) {
      out.push({ kind: "hunk", text: line });
    } else if (line.startsWith("+")) {
      out.push({ kind: "add", text: line.slice(1) });
    } else if (line.startsWith("-")) {
      out.push({ kind: "remove", text: line.slice(1) });
    } else {
      out.push({ kind: "context", text: line.startsWith(" ") ? line.slice(1) : line });
    }
  }
  return out;
}

export function DiffRenderer({ body, t }: Props) {
  if (!body || !body.trim()) {
    return (
      <div
        style={{
          padding: "8px 12px",
          fontSize: 12,
          color: t.textMuted,
          fontStyle: "italic",
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 8,
          background: t.codeBg,
        }}
      >
        (no changes)
      </div>
    );
  }

  const lines = parseDiff(body);

  return (
    <div
      style={{
        display: "block",
        borderRadius: 8,
        border: `1px solid ${t.surfaceBorder}`,
        background: t.codeBg,
        fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
        fontSize: 12,
        lineHeight: 1.5,
        overflow: "hidden",
        maxHeight: 400,
        overflowY: "auto",
      }}
    >
      {lines.map((line, i) => {
        const styles = lineStyles(line, t);
        return (
          <div
            key={i}
            style={{
              display: "flex", flexDirection: "row",
              minHeight: "1.5em",
              ...styles.row,
            }}
          >
            <div
              style={{
                flex: "0 0 18px",
                textAlign: "center",
                color: styles.gutterColor,
                userSelect: "none",
              }}
            >
              {styles.gutter}
            </div>
            <div
              style={{
                flex: 1,
                padding: "0 8px",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                color: styles.textColor,
              }}
            >
              {line.text || "\u00a0"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function lineStyles(line: DiffLine, t: ThemeTokens) {
  switch (line.kind) {
    case "add":
      return {
        row: { background: t.successSubtle },
        gutter: "+",
        gutterColor: t.success,
        textColor: t.contentText,
      };
    case "remove":
      return {
        row: { background: t.dangerSubtle },
        gutter: "−",
        gutterColor: t.danger,
        textColor: t.contentText,
      };
    case "hunk":
      return {
        row: { background: t.overlayLight },
        gutter: "",
        gutterColor: t.textDim,
        textColor: t.textMuted,
      };
    case "header":
      return {
        row: { background: "transparent" },
        gutter: "",
        gutterColor: t.textDim,
        textColor: t.textDim,
      };
    case "context":
    default:
      return {
        row: { background: "transparent" },
        gutter: "",
        gutterColor: t.textDim,
        textColor: t.contentText,
      };
  }
}
