import { useState } from "react";
import { ActionButton, SettingsControlRow, SettingsSearchBox, StatusBadge } from "@/src/components/shared/SettingsControls";
import { apiFetch } from "@/src/api/client";

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
    <div className="flex flex-col gap-2">
      <div className="text-[11px] leading-relaxed text-text-muted">
        Search archived sections by topic, transcript content, or semantic similarity.
        This uses the same search the bot sees via <code className="rounded bg-surface-overlay px-1 py-px font-mono text-[10px] text-text-muted">read_conversation_history</code>.
      </div>
      <div className="flex items-center gap-1.5">
        <SettingsSearchBox
          value={query}
          onChange={setQuery}
          onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }}
          placeholder="Search sections..."
        />
        <ActionButton
          label={loading ? "Searching..." : "Search"}
          onPress={doSearch}
          disabled={loading || !query.trim()}
          variant="primary"
          size="small"
        />
      </div>

      {error && (
        <div className="py-1 text-[11px] text-danger">{error}</div>
      )}

      {results !== null && results.length === 0 && (
        <div className="py-1 text-[11px] text-text-dim">
          No sections found matching your query.
        </div>
      )}

      {results && results.length > 0 && (
        <div className="flex max-h-[400px] flex-col gap-1 overflow-y-auto">
          {results.map((r) => {
            const dateStr = r.section.period_start
              ? new Date(r.section.period_start).toLocaleDateString(undefined, { month: "short", day: "numeric" })
              : "";
            const badge = sourceLabel(r.source);
            return (
              <SettingsControlRow
                key={r.section.id}
                leading={<span className="font-mono text-[10px] text-text-dim">#{r.section.sequence}</span>}
                title={r.section.title}
                description={
                  <div className="space-y-1">
                    <div>
                  {r.section.summary.length > 200 ? r.section.summary.slice(0, 200) + "..." : r.section.summary}
                    </div>
                {r.snippet && (
                      <div className="whitespace-pre-wrap rounded bg-surface/80 px-2 py-1 font-mono text-[10px] leading-snug text-text-muted">
                    {r.snippet}
                  </div>
                )}
                  </div>
                }
                meta={
                  <div className="flex items-center gap-2">
                    {badge && <StatusBadge label={badge} variant="info" />}
                    <span>{r.section.message_count} msgs</span>
                    {dateStr && <span>{dateStr}</span>}
                  </div>
                }
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
