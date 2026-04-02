import { useState, useMemo } from "react";
import { LayoutList, Users } from "lucide-react";
import { useJournal } from "../hooks/useMC";
import { useScope } from "../lib/ScopeContext";
import { botDotColor } from "../lib/colors";
import { dateLabel } from "../lib/dates";
import MarkdownViewer from "../components/MarkdownViewer";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import EmptyState from "../components/EmptyState";
import InfoPanel from "../components/InfoPanel";
import ScopeToggle from "../components/ScopeToggle";

const DAY_OPTIONS = [7, 14, 30, 60];
const PREVIEW_LINES = 8;

export default function Journal() {
  const { scope } = useScope();
  const [days, setDays] = useState(7);
  const [botFilter, setBotFilter] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<"date" | "bot">("date");

  const { data: entries, isLoading, error, refetch } = useJournal(days, scope);

  const bots = useMemo(() => {
    if (!entries) return [];
    const seen = new Map<string, string>();
    for (const e of entries) {
      if (!seen.has(e.bot_id)) seen.set(e.bot_id, e.bot_name);
    }
    return Array.from(seen, ([id, name]) => ({ id, name }));
  }, [entries]);

  const filtered = useMemo(() => {
    if (!entries) return [];
    if (!botFilter) return entries;
    return entries.filter((e) => e.bot_id === botFilter);
  }, [entries, botFilter]);

  const grouped = useMemo(() => {
    const groups = new Map<string, typeof filtered>();
    for (const e of filtered) {
      const key = groupBy === "date" ? e.date : `${e.bot_name} (${e.bot_id.slice(0, 8)})`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(e);
    }
    return Array.from(groups);
  }, [filtered, groupBy]);

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-content">Journal</h1>
          <p className="text-sm text-content-dim mt-1">Daily logs from your bots</p>
        </div>
        <ScopeToggle />
      </div>

      <InfoPanel
        id="journal"
        description="Daily logs written by bots. Requires memory_scheme: workspace-files."
        tips={[
          "Group by date or by bot using the toggle above.",
          "Entries come from each bot's memory/logs/ directory.",
        ]}
      />

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2 mb-6">
        {/* Day range */}
        <div className="flex gap-1">
          {DAY_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                days === d
                  ? "border-accent bg-accent text-white"
                  : "border-surface-3 text-content-muted hover:text-content"
              }`}
            >
              {d}d
            </button>
          ))}
        </div>

        <div className="w-px h-5 bg-surface-3" />

        {/* Group toggle — single icon button */}
        <button
          onClick={() => setGroupBy(groupBy === "date" ? "bot" : "date")}
          className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-md border border-surface-3 text-content-muted hover:text-content transition-colors"
          title={`Group by ${groupBy === "date" ? "bot" : "date"}`}
        >
          {groupBy === "date" ? <LayoutList size={13} /> : <Users size={13} />}
          <span>By {groupBy}</span>
        </button>

        {/* Bot filter pills with color dots */}
        {bots.length > 1 && (
          <>
            <div className="w-px h-5 bg-surface-3" />
            <button
              onClick={() => setBotFilter(null)}
              className={`px-2.5 py-1 text-xs rounded-full transition-colors ${
                !botFilter ? "bg-accent/15 text-accent-hover" : "text-content-dim hover:text-content-muted"
              }`}
            >
              All
            </button>
            {bots.map((b) => (
              <button
                key={b.id}
                onClick={() => setBotFilter(b.id)}
                className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full transition-colors ${
                  botFilter === b.id ? "bg-accent/15 text-accent-hover" : "text-content-dim hover:text-content-muted"
                }`}
              >
                <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: botDotColor(b.id) }} />
                {b.name}
              </button>
            ))}
          </>
        )}
      </div>

      {/* Content */}
      {isLoading ? (
        <LoadingSpinner />
      ) : error ? (
        <ErrorBanner message={error.message} onRetry={() => refetch()} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="◉"
          title="No journal entries"
          description="Daily logs will appear here as bots work. Requires memory_scheme: workspace-files."
          tips={[
            "Set memory_scheme: workspace-files in your bot YAML.",
            "Logs appear after the bot's next interaction.",
          ]}
          links={[{ label: "Go to Setup", to: "/setup" }]}
        />
      ) : (
        <div className="space-y-6">
          {grouped.map(([key, items]) => {
            const isToday = groupBy === "date" && dateLabel(key) === "Today";
            const label = groupBy === "date" ? dateLabel(key) : key;

            return (
              <div key={key}>
                <div className="flex items-center gap-2 mb-3 sticky top-0 bg-surface-0 py-1 z-10">
                  <h2 className="text-sm font-semibold text-content-muted">{label}</h2>
                  {isToday && (
                    <span className="px-1.5 py-px text-[10px] font-semibold rounded-full bg-accent/15 text-accent-hover">
                      Today
                    </span>
                  )}
                  <span className="text-[10px] text-content-dim">{items.length} {items.length === 1 ? "entry" : "entries"}</span>
                </div>
                <div className="space-y-3">
                  {items.map((entry, idx) => (
                    <CollapsibleEntry key={`${entry.bot_id}-${entry.date}-${idx}`} entry={entry} groupBy={groupBy} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsible entry with preview
// ---------------------------------------------------------------------------

function CollapsibleEntry({
  entry,
  groupBy,
}: {
  entry: { bot_id: string; bot_name: string; date: string; content: string };
  groupBy: "date" | "bot";
}) {
  const [expanded, setExpanded] = useState(false);
  const lines = entry.content.split("\n");
  const isLong = lines.length > PREVIEW_LINES;
  const previewContent = isLong && !expanded
    ? lines.slice(0, PREVIEW_LINES).join("\n")
    : entry.content;
  const remaining = lines.length - PREVIEW_LINES;

  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
      <div className="flex items-center gap-2 mb-2">
        {groupBy === "date" && (
          <>
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: botDotColor(entry.bot_id) }} />
            <span className="text-xs font-medium text-accent-hover">{entry.bot_name}</span>
          </>
        )}
        {groupBy === "bot" && (
          <span className="text-xs text-content-dim">{entry.date}</span>
        )}
      </div>
      <MarkdownViewer content={previewContent} />
      {isLong && !expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="mt-2 text-xs text-content-dim hover:text-content-muted transition-colors"
        >
          {remaining} more line{remaining !== 1 ? "s" : ""}... ▾
        </button>
      )}
      {isLong && expanded && (
        <button
          onClick={() => setExpanded(false)}
          className="mt-2 text-xs text-content-dim hover:text-content-muted transition-colors"
        >
          Collapse ▴
        </button>
      )}
    </div>
  );
}
