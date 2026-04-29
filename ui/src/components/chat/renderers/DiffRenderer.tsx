/**
 * Unified-diff envelope renderer.
 *
 * Used for `application/vnd.spindrel.diff+text`. Parses lines that start
 * with `+`/`-`/` `/`@@` and renders them with success/danger background
 * tints from the existing theme tokens. The +/− gutter is fixed-width so
 * long lines wrap inside the line's content cell rather than offsetting
 * subsequent lines.
 *
 * Line-number gutter: each row carries the source-side line number (for
 * removals + context) and target-side line number (for additions + context),
 * derived from the `@@ -O,c +N,c @@` hunk headers. Numbers are rendered in
 * tabular-nums so column widths stay stable.
 *
 * Empty diff body → "(no changes)" placeholder.
 */
import type { ThemeTokens } from "../../../theme/tokens";
import type { ToolCallSummary } from "../../../types/api";
import type { RichRendererVariant } from "./genericRendererChrome";

interface Props {
  body: string;
  rendererVariant?: RichRendererVariant;
  summary?: ToolCallSummary | null;
  t: ThemeTokens;
}

type DiffLine =
  | { kind: "add"; text: string; newNo: number }
  | { kind: "remove"; text: string; oldNo: number }
  | { kind: "context"; text: string; oldNo: number; newNo: number }
  | { kind: "hunk"; text: string; oldStart: number; newStart: number }
  | { kind: "header"; text: string };

const HUNK_RE = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/;

export function parseDiff(body: string): DiffLine[] {
  const out: DiffLine[] = [];
  let oldNo = 0;
  let newNo = 0;
  const rawLines = body.split("\n");
  // Drop a trailing empty line caused by a body that ends with "\n" — it isn't
  // part of the diff and would otherwise advance the counters by one.
  if (rawLines.length > 0 && rawLines[rawLines.length - 1] === "") {
    rawLines.pop();
  }
  for (const line of rawLines) {
    if (line.startsWith("+++") || line.startsWith("---")) {
      out.push({ kind: "header", text: line });
    } else if (line.startsWith("@@")) {
      const m = HUNK_RE.exec(line);
      if (m) {
        oldNo = parseInt(m[1], 10);
        newNo = parseInt(m[2], 10);
        out.push({ kind: "hunk", text: line, oldStart: oldNo, newStart: newNo });
      } else {
        out.push({ kind: "hunk", text: line, oldStart: 0, newStart: 0 });
      }
    } else if (line.startsWith("\\")) {
      // "\ No newline at end of file" and similar metadata — render as
      // header-style so it carries no line numbers and doesn't advance counters.
      out.push({ kind: "header", text: line });
    } else if (line.startsWith("+")) {
      out.push({ kind: "add", text: line.slice(1), newNo });
      newNo += 1;
    } else if (line.startsWith("-")) {
      out.push({ kind: "remove", text: line.slice(1), oldNo });
      oldNo += 1;
    } else {
      // Context — `unified_diff` prefixes context lines with a single space,
      // but be lenient if the leading space is missing.
      const text = line.startsWith(" ") ? line.slice(1) : line;
      out.push({ kind: "context", text, oldNo, newNo });
      oldNo += 1;
      newNo += 1;
    }
  }
  return out;
}

const CODE_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

export function DiffRenderer({ body, rendererVariant = "default-chat", summary, t }: Props) {
  const isTerminal = rendererVariant === "terminal-chat";
  if (!body || !body.trim()) {
    return (
      <div
        style={{
          padding: isTerminal ? "6px 0" : "8px 12px",
          fontSize: isTerminal ? 11 : 12,
          color: t.textMuted,
          fontStyle: "italic",
          border: isTerminal ? "none" : `1px solid ${t.surfaceBorder}`,
          borderRadius: isTerminal ? 0 : 8,
          background: isTerminal ? "transparent" : t.codeBg,
          fontFamily: CODE_FONT_STACK,
        }}
      >
        (no changes)
      </div>
    );
  }

  const lines = parseDiff(body).filter((line) => !isTerminal || line.kind !== "header");
  const diffSummary =
    isTerminal && summary?.kind === "diff" && summary.subject_type === "file"
      ? summary
      : null;

  // Width of each line-number column: enough digits for the largest number we
  // expect to render, capped sensibly.
  const maxNo = lines.reduce((acc, line) => {
    if (line.kind === "add") return Math.max(acc, line.newNo);
    if (line.kind === "remove") return Math.max(acc, line.oldNo);
    if (line.kind === "context") return Math.max(acc, line.oldNo, line.newNo);
    return acc;
  }, 0);
  const numCh = Math.max(2, String(maxNo).length);
  // ch units keep the gutter monospace-aligned regardless of font.
  const numCol = `${numCh + 1}ch`;

  return (
    <div style={{ fontFamily: CODE_FONT_STACK }}>
      {diffSummary && (
        <DiffTitle summary={diffSummary} t={t} />
      )}
      <div
        style={{
          display: "block",
          borderRadius: isTerminal ? 0 : 8,
          border: isTerminal ? "none" : `1px solid ${t.surfaceBorder}`,
          background: isTerminal ? "transparent" : t.codeBg,
          fontSize: isTerminal ? 11 : 12,
          lineHeight: isTerminal ? 1.42 : 1.5,
          overflow: "hidden",
          maxHeight: isTerminal ? "none" : 400,
          overflowY: isTerminal ? "visible" : "auto",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {lines.map((line, i) => {
          const styles = lineStyles(line, t, isTerminal);
          const { oldNo, newNo } = lineNumbers(line);
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
                  flex: `0 0 ${numCol}`,
                  textAlign: "right",
                  padding: "0 6px 0 4px",
                  color: t.textDim,
                  userSelect: "none",
                  opacity: 0.9,
                }}
              >
                {oldNo ?? ""}
              </div>
              <div
                style={{
                  flex: `0 0 ${numCol}`,
                  textAlign: "right",
                  padding: "0 6px 0 0",
                  color: t.textDim,
                  userSelect: "none",
                  opacity: 0.9,
                }}
              >
                {newNo ?? ""}
              </div>
              <div
                style={{
                  flex: isTerminal ? "0 0 20px" : "0 0 16px",
                  textAlign: "center",
                  color: styles.gutterColor,
                  userSelect: "none",
                  paddingTop: isTerminal ? 1 : 0,
                }}
              >
                {styles.gutter}
              </div>
              <div
                style={{
                  flex: 1,
                  padding: isTerminal ? "1px 8px 1px 2px" : "0 8px",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  color: styles.textColor,
                }}
              >
                {line.text || " "}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function lineNumbers(line: DiffLine): { oldNo: number | null; newNo: number | null } {
  switch (line.kind) {
    case "add":
      return { oldNo: null, newNo: line.newNo };
    case "remove":
      return { oldNo: line.oldNo, newNo: null };
    case "context":
      return { oldNo: line.oldNo, newNo: line.newNo };
    case "hunk":
    case "header":
      return { oldNo: null, newNo: null };
  }
}

function DiffTitle({ summary, t }: { summary: ToolCallSummary; t: ThemeTokens }) {
  const label = summary.label || summary.path || summary.target_label || "Edited file";
  const stats = summary.diff_stats;
  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "baseline",
        gap: 4,
        margin: "0 0 6px 0",
        color: t.textMuted,
        fontSize: 11.5,
        lineHeight: 1.4,
      }}
    >
      <span style={{ color: t.text, fontWeight: 600 }}>{label}</span>
      {stats && (
        <span>
          (
          <span style={{ color: t.success }}>+{stats.additions}</span>
          {" "}
          <span style={{ color: t.danger }}>-{stats.deletions}</span>
          )
        </span>
      )}
    </div>
  );
}

function lineStyles(line: DiffLine, t: ThemeTokens, isTerminal: boolean) {
  switch (line.kind) {
    case "add":
      return {
        row: { background: isTerminal ? "rgba(34, 197, 94, 0.18)" : t.successSubtle },
        gutter: "+",
        gutterColor: t.success,
        textColor: isTerminal ? t.text : t.contentText,
      };
    case "remove":
      return {
        row: { background: isTerminal ? "rgba(239, 68, 68, 0.18)" : t.dangerSubtle },
        gutter: "−",
        gutterColor: t.danger,
        textColor: isTerminal ? t.text : t.contentText,
      };
    case "hunk":
      return {
        row: { background: isTerminal ? "transparent" : t.overlayLight },
        gutter: "@",
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
