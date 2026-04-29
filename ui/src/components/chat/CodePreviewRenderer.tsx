import type { ReactNode } from "react";
import type { ThemeTokens } from "../../theme/tokens";

export const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";
export const CODE_FONT_STACK = "'Menlo', 'Monaco', 'Consolas', monospace";

type CodeLanguage = "html" | "css" | "js" | "json" | "shell" | "text";

function targetExtension(target: string | null | undefined): string {
  const clean = (target ?? "").split(/[?#]/)[0] ?? "";
  const match = clean.match(/\.([a-z0-9]+)$/i);
  return match?.[1]?.toLowerCase() ?? "";
}

export function detectCodePreviewLanguage(text: string, target: string | null | undefined): CodeLanguage {
  const ext = targetExtension(target);
  if (["html", "htm", "xml", "svg"].includes(ext)) return "html";
  if (["css", "scss", "sass"].includes(ext)) return "css";
  if (["js", "jsx", "ts", "tsx", "mjs", "cjs"].includes(ext)) return "js";
  if (["json", "jsonc"].includes(ext)) return "json";
  if (["sh", "bash", "zsh"].includes(ext)) return "shell";
  const trimmed = text.trimStart();
  if (/^(<!doctype\s+html|<html[\s>]|<\w[\s>])/i.test(trimmed)) return "html";
  if (/^[{\[]/.test(trimmed)) return "json";
  if (/^([.#]?[a-z0-9_-]+\s*\{|:[\w-]+\s*\{)/i.test(trimmed)) return "css";
  if (/\b(function|const|let|import|export|interface|type)\b/.test(trimmed)) return "js";
  return "text";
}

export function looksLikeCodePreview(text: string, target: string | null | undefined): boolean {
  if (detectCodePreviewLanguage(text, target) !== "text") return true;
  const lines = text.split(/\r?\n/);
  const numbered = lines.filter((line, index) => {
    const match = line.match(/^\s*(\d+)\s/);
    return match && Number(match[1]) === index + 1;
  }).length;
  return numbered >= Math.min(3, Math.max(1, lines.length));
}

function renderHtmlTag(part: string, t: ThemeTokens): ReactNode {
  const tag = part.match(/^(<\/?)([A-Za-z][\w:-]*)(.*?)(\/?>)$/);
  if (!tag) return <span style={{ color: t.accent }}>{part}</span>;
  const attrs = tag[3]
    .split(/(\s+[A-Za-z_:][\w:.-]*)(=)("[^"]*"|'[^']*'|[^\s"'=<>`]+)?/g)
    .filter((token) => token.length > 0);
  return (
    <>
      <span style={{ color: t.textDim }}>{tag[1]}</span>
      <span style={{ color: t.accent }}>{tag[2]}</span>
      {attrs.map((token, index) => {
        if (/^\s+[A-Za-z_:][\w:.-]*$/.test(token)) return <span key={index} style={{ color: t.warning }}>{token}</span>;
        if (token === "=") return <span key={index} style={{ color: t.textDim }}>{token}</span>;
        if (/^("[^"]*"|'[^']*'|[^\s"'=<>`]+)$/.test(token)) return <span key={index} style={{ color: t.success }}>{token}</span>;
        return <span key={index} style={{ color: t.textMuted }}>{token}</span>;
      })}
      <span style={{ color: t.textDim }}>{tag[4]}</span>
    </>
  );
}

function renderHighlightedLine(line: string, language: CodeLanguage, t: ThemeTokens): ReactNode {
  if (!line) return " ";
  if (language === "html") {
    const parts = line.split(/(<!--.*?-->|<\/?[A-Za-z][^>]*>|"[^"]*"|'[^']*')/g).filter(Boolean);
    return parts.map((part, index) => {
      if (part.startsWith("<!--")) return <span key={index} style={{ color: t.textDim }}>{part}</span>;
      if (part.startsWith("<")) return <span key={index}>{renderHtmlTag(part, t)}</span>;
      if ((part.startsWith("\"") && part.endsWith("\"")) || (part.startsWith("'") && part.endsWith("'"))) {
        return <span key={index} style={{ color: t.success }}>{part}</span>;
      }
      return <span key={index} style={{ color: t.textMuted }}>{part}</span>;
    });
  }
  if (language === "json" || language === "js") {
    const parts = line
      .split(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|\b(?:const|let|var|function|return|import|export|from|type|interface|class|new|if|else|true|false|null)\b|\b\d+(?:\.\d+)?\b|\/\/.*$)/g)
      .filter(Boolean);
    return parts.map((part, index) => {
      if (part.startsWith("//")) return <span key={index} style={{ color: t.textDim }}>{part}</span>;
      if ((part.startsWith("\"") && part.endsWith("\"")) || (part.startsWith("'") && part.endsWith("'"))) return <span key={index} style={{ color: t.success }}>{part}</span>;
      if (/^\d/.test(part)) return <span key={index} style={{ color: t.warning }}>{part}</span>;
      if (/^(const|let|var|function|return|import|export|from|type|interface|class|new|if|else|true|false|null)$/.test(part)) return <span key={index} style={{ color: t.purple }}>{part}</span>;
      return <span key={index} style={{ color: t.textMuted }}>{part}</span>;
    });
  }
  if (language === "css") {
    const property = line.match(/^(\s*[-_a-zA-Z][-_a-zA-Z0-9]*)(\s*:)(.*)$/);
    if (property) {
      return (
        <>
          <span style={{ color: t.accent }}>{property[1]}</span>
          <span style={{ color: t.textDim }}>{property[2]}</span>
          <span style={{ color: t.success }}>{property[3]}</span>
        </>
      );
    }
  }
  if (language === "shell") {
    const listing = line.match(/^([dl-][rwx-]{9})(\s+\d+\s+\S+\s+\S+\s+\S+\s+\w+\s+\d+\s+[\d:]+\s+)(.*)$/);
    if (listing) {
      return (
        <>
          <span style={{ color: t.textDim }}>{listing[1]}</span>
          <span style={{ color: t.textMuted }}>{listing[2]}</span>
          <span style={{ color: listing[1].startsWith("d") ? t.accent : t.textMuted }}>{listing[3]}</span>
        </>
      );
    }
  }
  return <span style={{ color: t.textMuted }}>{line}</span>;
}

function splitPreviewLines(text: string): { number: string; text: string }[] {
  const lines = text.split(/\r?\n/);
  const numbered = lines.map((line) => line.match(/^\s*(\d+)\s(.*)$/));
  const sequentialMatches = numbered.filter((match, index) => match && Number(match[1]) === index + 1).length;
  const hasSequentialGutter = sequentialMatches >= Math.min(3, Math.max(1, lines.length));
  return lines.map((line, index) => {
    const match = hasSequentialGutter ? numbered[index] : null;
    return { number: match?.[1] ?? String(index + 1), text: match?.[2] ?? line };
  });
}

export function CodePreviewRenderer({
  text,
  target,
  t,
  isError = false,
  maxLines,
  testId = "terminal-code-output",
}: {
  text: string;
  target?: string | null;
  t: ThemeTokens;
  isError?: boolean;
  maxLines?: number;
  testId?: string;
}) {
  const language = detectCodePreviewLanguage(text, target);
  const rows = splitPreviewLines(text);
  const visibleRows = maxLines ? rows.slice(0, maxLines) : rows;
  const hiddenRows = maxLines && rows.length > maxLines ? rows.length - maxLines : 0;
  return (
    <div
      data-testid={testId}
      className="min-w-0 max-w-full overflow-hidden"
      style={{
        borderLeft: `1px solid ${isError ? t.dangerBorder : t.surfaceBorder}`,
        marginLeft: 6,
        marginTop: 3,
        paddingLeft: 10,
        fontFamily: TERMINAL_FONT_STACK,
        fontSize: 11.5,
        lineHeight: 1.45,
      }}
    >
      {visibleRows.map((row, index) => (
        <div
          key={`${row.number}:${index}`}
          style={{
            display: "grid",
            gridTemplateColumns: "4ch minmax(0, 1fr)",
            columnGap: 10,
            alignItems: "start",
            maxWidth: "100%",
          }}
        >
          <span
            style={{
              color: t.textDim,
              fontVariantNumeric: "tabular-nums",
              textAlign: "right",
              userSelect: "none",
            }}
          >
            {row.number}
          </span>
          <span
            style={{
              color: isError ? t.dangerMuted : t.textMuted,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              overflowWrap: "anywhere",
            }}
          >
            {renderHighlightedLine(row.text, language, t)}
          </span>
        </div>
      ))}
      {hiddenRows ? (
        <div style={{ color: t.textDim, paddingLeft: "calc(4ch + 10px)" }}>
          ... {hiddenRows} more lines
        </div>
      ) : null}
    </div>
  );
}
