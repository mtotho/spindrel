/**
 * File listing renderer for `application/vnd.spindrel.file-listing+json`.
 *
 * Handles three shapes emitted by `app/tools/local/file_ops.py`:
 *  - `list`  → `{ path, entries: [{name, type, size}] }`
 *  - `glob`  → `{ kind: "glob", paths, count, truncated }`
 *  - `grep`  → `{ kind: "grep", matches: [{file, line, text}], count, files_scanned, truncated }`
 *
 * Listings are dense by design — most file ops return 10–500 entries
 * and the user wants to skim, not scroll.
 */
import { Folder, FileText, Search, ChevronRight } from "lucide-react";
import type { ThemeTokens } from "../../../theme/tokens";

interface Props {
  body: string;
  t: ThemeTokens;
}

interface ListEntry {
  name: string;
  type: "dir" | "file";
  size?: number;
}

interface GrepMatch {
  file: string;
  line: number;
  text: string;
}

interface ListingShape {
  // list
  path?: string;
  entries?: ListEntry[];
  // glob
  paths?: string[];
  // grep
  matches?: GrepMatch[];
  files_scanned?: number;
  // common
  kind?: "glob" | "grep";
  count?: number;
  truncated?: boolean;
}

export function FileListingRenderer({ body, t }: Props) {
  let parsed: ListingShape;
  try {
    parsed = JSON.parse(body);
  } catch {
    return (
      <pre style={{ fontSize: 12, color: t.textMuted, whiteSpace: "pre-wrap" }}>{body}</pre>
    );
  }

  if (parsed.matches) {
    return <GrepListing data={parsed} t={t} />;
  }
  if (parsed.paths) {
    return <GlobListing data={parsed} t={t} />;
  }
  if (parsed.entries) {
    return <DirListing data={parsed} t={t} />;
  }

  return (
    <pre style={{ fontSize: 12, color: t.textMuted, whiteSpace: "pre-wrap" }}>{body}</pre>
  );
}

function listingShell(t: ThemeTokens) {
  return {
    border: `1px solid ${t.surfaceBorder}`,
    borderRadius: 6,
    background: t.codeBg,
    fontFamily: "'Menlo', monospace",
    fontSize: 12,
    color: t.contentText,
    maxHeight: 360,
    overflowY: "auto" as const,
  };
}

function DirListing({ data, t }: { data: ListingShape; t: ThemeTokens }) {
  const entries = data.entries ?? [];
  return (
    <div style={listingShell(t)}>
      {data.path && (
        <div
          style={{
            padding: "6px 12px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
            color: t.textMuted,
            fontSize: 11,
          }}
        >
          <Folder size={11} style={{ display: "inline-block", marginRight: 4, verticalAlign: "middle" }} color={t.textMuted} />
          {data.path} · {entries.length} entries
        </div>
      )}
      {entries.map((e, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "3px 12px",
            color: e.type === "dir" ? t.accent : t.contentText,
          }}
        >
          {e.type === "dir" ? (
            <Folder size={12} color={t.accent} />
          ) : (
            <FileText size={12} color={t.textMuted} />
          )}
          <span style={{ flex: 1 }}>{e.name}{e.type === "dir" ? "/" : ""}</span>
          {e.type === "file" && e.size != null && (
            <span style={{ color: t.textDim, fontSize: 11 }}>{formatSize(e.size)}</span>
          )}
        </div>
      ))}
    </div>
  );
}

function GlobListing({ data, t }: { data: ListingShape; t: ThemeTokens }) {
  const paths = data.paths ?? [];
  return (
    <div style={listingShell(t)}>
      <div
        style={{
          padding: "6px 12px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          color: t.textMuted,
          fontSize: 11,
        }}
      >
        <Search size={11} style={{ display: "inline-block", marginRight: 4, verticalAlign: "middle" }} color={t.textMuted} />
        {paths.length} file(s){data.truncated ? " (truncated)" : ""}
      </div>
      {paths.map((p, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "3px 12px",
          }}
        >
          <FileText size={12} color={t.textDim} />
          <span>{p}</span>
        </div>
      ))}
    </div>
  );
}

function GrepListing({ data, t }: { data: ListingShape; t: ThemeTokens }) {
  const matches = data.matches ?? [];
  // Group by file so the user sees one heading per file with all matching lines beneath.
  const grouped = new Map<string, GrepMatch[]>();
  for (const m of matches) {
    const arr = grouped.get(m.file) ?? [];
    arr.push(m);
    grouped.set(m.file, arr);
  }

  return (
    <div style={listingShell(t)}>
      <div
        style={{
          padding: "6px 12px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          color: t.textMuted,
          fontSize: 11,
        }}
      >
        <Search size={11} style={{ display: "inline-block", marginRight: 4, verticalAlign: "middle" }} color={t.textMuted} />
        {matches.length} match(es) in {grouped.size} file(s)
        {data.files_scanned != null ? ` · scanned ${data.files_scanned}` : ""}
        {data.truncated ? " · truncated" : ""}
      </div>
      {[...grouped.entries()].map(([file, hits]) => (
        <div key={file}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "4px 12px 2px",
              color: t.accent,
              borderTop: `1px solid ${t.surfaceBorder}`,
            }}
          >
            <ChevronRight size={11} color={t.accent} />
            <span>{file}</span>
            <span style={{ color: t.textDim, marginLeft: 4 }}>({hits.length})</span>
          </div>
          {hits.map((m, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                gap: 8,
                padding: "1px 12px 1px 24px",
                color: t.contentText,
              }}
            >
              <span style={{ color: t.textDim, minWidth: 36, textAlign: "right" }}>{m.line}</span>
              <span style={{ flex: 1, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{m.text}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
