import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { Search } from "lucide-react";

type SearchResult = {
  section: {
    id: string;
    sequence: number;
    title: string;
    summary: string;
    message_count: number;
    period_start: string | null;
    tags: string[];
  };
  source: string;
  snippet: string | null;
};

export function SectionSearch({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doSearch = async () => {
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ results: SearchResult[] }>(
        `/api/v1/admin/channels/${channelId}/sections/search?q=${encodeURIComponent(q)}`
      );
      setResults(data.results);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Search failed");
    } finally {
      setLoading(false);
    }
  };

  const sourceLabel = (source: string) => {
    if (source === "content") return "content match";
    if (source === "semantic") return "semantic match";
    return null;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.5" }}>
        Search archived sections by topic, transcript content, or semantic similarity.
        This uses the same search the bot sees via <code style={{ color: t.codeText }}>read_conversation_history</code>.
      </div>
      <div style={{ display: "flex", flexDirection: "row", gap: 6, alignItems: "center" }}>
        <div style={{
          flex: 1, display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.inputBorder}`,
          borderRadius: 6, padding: "6px 10px",
        }}>
          <Search size={14} color={t.textDim} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }}
            placeholder="Search sections..."
            style={{
              flex: 1, background: "none", border: "none", outline: "none",
              color: t.text, fontSize: 12, fontFamily: "inherit",
            }}
          />
        </div>
        <button
          onClick={doSearch}
          disabled={loading || !query.trim()}
          style={{
            padding: "6px 14px", borderRadius: 6, border: "none",
            background: t.accent, color: "#fff", fontSize: 11, fontWeight: 600,
            cursor: loading || !query.trim() ? "not-allowed" : "pointer",
            opacity: loading || !query.trim() ? 0.5 : 1,
          }}
        >
          {loading ? <Spinner size={14} color="#fff" /> : "Search"}
        </button>
      </div>

      {error && (
        <div style={{ fontSize: 11, color: t.danger, padding: "4px 0" }}>{error}</div>
      )}

      {results !== null && results.length === 0 && (
        <div style={{ fontSize: 11, color: t.textDim, padding: "4px 0" }}>
          No sections found matching your query.
        </div>
      )}

      {results && results.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 400, overflowY: "auto" }}>
          {results.map((r) => {
            const dateStr = r.section.period_start
              ? new Date(r.section.period_start).toLocaleDateString(undefined, { month: "short", day: "numeric" })
              : "";
            const badge = sourceLabel(r.source);
            return (
              <div key={r.section.id} style={{
                padding: "8px 12px", background: t.inputBg,
                border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6,
              }}>
                <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 10, color: t.textDim }}>#{r.section.sequence}</span>
                  <span style={{ fontSize: 12, color: t.text, flex: 1 }}>{r.section.title}</span>
                  {badge && (
                    <span style={{
                      fontSize: 9, color: t.accent, background: t.accentSubtle,
                      padding: "1px 6px", borderRadius: 8, fontWeight: 600, flexShrink: 0,
                    }}>{badge}</span>
                  )}
                  <span style={{ fontSize: 10, color: t.textDim }}>{r.section.message_count} msgs</span>
                  {dateStr && <span style={{ fontSize: 10, color: t.textDim }}>{dateStr}</span>}
                </div>
                <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4, lineHeight: "1.4" }}>
                  {r.section.summary.length > 200 ? r.section.summary.slice(0, 200) + "..." : r.section.summary}
                </div>
                {r.snippet && (
                  <div style={{
                    marginTop: 4, padding: "4px 8px", background: t.codeBg,
                    border: `1px solid ${t.codeBorder}`, borderRadius: 4,
                    fontSize: 10, color: t.textMuted, fontFamily: "monospace",
                    lineHeight: "1.4", whiteSpace: "pre-wrap",
                  }}>
                    {r.snippet}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
