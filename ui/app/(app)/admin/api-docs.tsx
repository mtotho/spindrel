import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Spinner } from "@/src/components/shared/Spinner";
import { FileCode, Search, Copy, Check } from "lucide-react";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";

function useApiDocs() {
  return useQuery({
    queryKey: ["api-docs-markdown"],
    queryFn: async () => {
      const { serverUrl } = useAuthStore.getState();
      if (!serverUrl) throw new Error("Server not configured");
      const token = getAuthToken();
      const res = await fetch(`${serverUrl}/api/v1/discover?detail=true`, {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      return res.text();
    },
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Minimal markdown renderer — handles headers, code blocks, tables, bold, lists
// ---------------------------------------------------------------------------

function renderMarkdown(md: string, t: ReturnType<typeof useThemeTokens>): React.ReactNode[] {
  const lines = md.split("\n");
  const nodes: React.ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Code block
    if (line.startsWith("```")) {
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      nodes.push(
        <pre key={key++} style={{
          padding: "12px 14px", background: t.surface, borderRadius: 6,
          border: `1px solid ${t.surfaceOverlay}`, fontSize: 12,
          fontFamily: "monospace", color: t.text, overflowX: "auto",
          margin: "4px 0", lineHeight: 1.5, whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}>
          {codeLines.join("\n")}
        </pre>
      );
      continue;
    }

    // Table — gather consecutive lines starting with |
    if (line.startsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      // Parse table
      const rows = tableLines
        .filter((l) => !l.match(/^\|\s*[-:]+/)) // skip separator rows
        .map((l) =>
          l.split("|").slice(1, -1).map((c) => c.trim())
        );
      if (rows.length > 0) {
        const header = rows[0];
        const body = rows.slice(1);
        nodes.push(
          <div key={key++} style={{ overflowX: "auto", margin: "4px 0" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${t.surfaceOverlay}` }}>
                  {header.map((cell, ci) => (
                    <th key={ci} style={{
                      textAlign: "left", padding: "6px 10px",
                      fontSize: 11, fontWeight: 600, color: t.textDim,
                    }}>
                      {cell}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {body.map((row, ri) => (
                  <tr key={ri} style={{ borderBottom: `1px solid ${t.surfaceOverlay}` }}>
                    {row.map((cell, ci) => (
                      <td key={ci} style={{
                        padding: "6px 10px", color: t.text, fontFamily: "monospace",
                        fontSize: 12, whiteSpace: "nowrap",
                      }}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      continue;
    }

    // Headings
    if (line.startsWith("# ")) {
      nodes.push(
        <h1 key={key++} style={{
          fontSize: 22, fontWeight: 700, color: t.text,
          margin: "20px 0 8px", borderBottom: `1px solid ${t.surfaceOverlay}`,
          paddingBottom: 8,
        }}>
          {line.slice(2)}
        </h1>
      );
      i++;
      continue;
    }
    if (line.startsWith("## ")) {
      nodes.push(
        <h2 key={key++} style={{
          fontSize: 17, fontWeight: 700, color: t.text,
          margin: "18px 0 6px",
        }}>
          {line.slice(3)}
        </h2>
      );
      i++;
      continue;
    }
    if (line.startsWith("### ")) {
      nodes.push(
        <h3 key={key++} style={{
          fontSize: 14, fontWeight: 600, color: t.textMuted,
          margin: "14px 0 4px",
        }}>
          {line.slice(4)}
        </h3>
      );
      i++;
      continue;
    }

    // List items
    if (line.match(/^\s*[-*]\s/)) {
      nodes.push(
        <div key={key++} style={{
          paddingLeft: 16, fontSize: 13, color: t.text,
          lineHeight: 1.6, margin: "2px 0",
        }}>
          <span style={{ color: t.textDim, marginRight: 6 }}>•</span>
          <InlineMarkdown text={line.replace(/^\s*[-*]\s/, "")} t={t} />
        </div>
      );
      i++;
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      nodes.push(<div key={key++} style={{ height: 6 }} />);
      i++;
      continue;
    }

    // Regular paragraph
    nodes.push(
      <p key={key++} style={{
        fontSize: 13, color: t.text, lineHeight: 1.6,
        margin: "2px 0",
      }}>
        <InlineMarkdown text={line} t={t} />
      </p>
    );
    i++;
  }

  return nodes;
}

function InlineMarkdown({ text, t }: { text: string; t: ReturnType<typeof useThemeTokens> }) {
  // Handle **bold**, `code`, and plain text
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let k = 0;

  while (remaining.length > 0) {
    // Bold
    const boldMatch = remaining.match(/\*\*(.+?)\*\*/);
    // Inline code
    const codeMatch = remaining.match(/`([^`]+)`/);

    // Find earliest match
    const boldIdx = boldMatch ? remaining.indexOf(boldMatch[0]) : -1;
    const codeIdx = codeMatch ? remaining.indexOf(codeMatch[0]) : -1;

    if (boldIdx === -1 && codeIdx === -1) {
      parts.push(<span key={k++}>{remaining}</span>);
      break;
    }

    const useCode = codeIdx !== -1 && (boldIdx === -1 || codeIdx < boldIdx);
    const match = useCode ? codeMatch! : boldMatch!;
    const idx = useCode ? codeIdx : boldIdx;

    if (idx > 0) {
      parts.push(<span key={k++}>{remaining.slice(0, idx)}</span>);
    }

    if (useCode) {
      parts.push(
        <code key={k++} style={{
          padding: "1px 5px", background: t.surface, borderRadius: 3,
          fontFamily: "monospace", fontSize: 12, color: t.accent,
        }}>
          {match[1]}
        </code>
      );
    } else {
      parts.push(<strong key={k++}>{match[1]}</strong>);
    }

    remaining = remaining.slice(idx + match[0].length);
  }

  return <>{parts}</>;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ApiDocsScreen() {
  const t = useThemeTokens();
  const { data: markdown, isLoading, isError, error } = useApiDocs();
  const { refreshing, onRefresh } = usePageRefresh([["api-docs-markdown"]]);
  const [filter, setFilter] = useState("");
  const [copied, setCopied] = useState(false);

  // Filter markdown lines if filter is active
  const filteredMarkdown = useMemo(() => {
    if (!markdown || !filter.trim()) return markdown ?? "";
    const lower = filter.toLowerCase();
    // Keep all headers and any line that matches the filter, plus surrounding context
    const lines = markdown.split("\n");
    const keep = new Set<number>();
    let lastHeader = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].startsWith("#")) lastHeader = i;
      if (lines[i].toLowerCase().includes(lower)) {
        if (lastHeader >= 0) keep.add(lastHeader);
        keep.add(i);
        // Keep a few lines of context
        for (let j = Math.max(0, i - 1); j <= Math.min(lines.length - 1, i + 2); j++) {
          keep.add(j);
        }
      }
    }
    return Array.from(keep).sort((a, b) => a - b).map((i) => lines[i]).join("\n");
  }, [markdown, filter]);

  const rendered = useMemo(() => {
    if (!filteredMarkdown) return null;
    return renderMarkdown(filteredMarkdown, t);
  }, [filteredMarkdown, t]);

  const handleCopy = async () => {
    if (!markdown) return;
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="API Reference"
        subtitle="Auto-generated from server routes"
        right={
          <div style={{ display: "flex", flexDirection: "row", gap: 8, alignItems: "center" }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 6,
              background: t.inputBg, borderRadius: 6,
              border: `1px solid ${t.surfaceOverlay}`,
              padding: "4px 10px",
            }}>
              <Search size={13} color={t.textDim} />
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter..."
                style={{
                  border: "none", outline: "none", background: "transparent",
                  color: t.text, fontSize: 12, width: 120,
                }}
              />
            </div>
            <button
              onClick={handleCopy}
              disabled={!markdown}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                padding: "6px 10px", fontSize: 11, fontWeight: 600,
                border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6,
                background: t.inputBg, color: t.textMuted, cursor: "pointer",
              }}
            >
              {copied ? <Check size={13} color={t.success} /> : <Copy size={13} />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        }
      />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, maxWidth: 900 }}
      >
        {isLoading && (
          <div style={{ padding: 40, textAlign: "center" }}>
            <Spinner color={t.accent} />
          </div>
        )}

        {isError && (
          <div style={{
            padding: 16, background: t.dangerSubtle,
            border: `1px solid ${t.dangerBorder}`, borderRadius: 8,
            fontSize: 13, color: t.danger,
          }}>
            Failed to load API docs: {(error as Error).message}
          </div>
        )}

        {rendered && (
          <div style={{
            background: t.inputBg, borderRadius: 8,
            border: `1px solid ${t.surfaceRaised}`,
            padding: "16px 20px",
          }}>
            {rendered}
          </div>
        )}

        {markdown && filter && filteredMarkdown?.trim() === "" && (
          <div style={{ padding: 24, textAlign: "center", fontSize: 13, color: t.textDim }}>
            No results matching "{filter}"
          </div>
        )}
      </RefreshableScrollView>
    </div>
  );
}
