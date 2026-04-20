/**
 * WidgetLogView — consumes the `spindrel.log` ring buffer forwarded via
 * postMessage from every live InteractiveHtmlRenderer iframe and rendered
 * as a two-pane list/detail beneath the Recent tab's segmented control.
 *
 * Read-only sibling to the tool-calls view: filter by level, click to
 * expand the full message, clear the in-memory buffer. Entries are
 * enriched at the host boundary with the emitting bot + pin + channel so
 * widget authors can trace a log line back to one concrete pin.
 */
import { useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import {
  useWidgetLogStore,
  type WidgetLogEntry,
  type WidgetLogLevel,
} from "@/src/stores/widgetLog";
import { formatRelativeTime } from "@/src/utils/format";

const LEVELS: { key: WidgetLogLevel | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "info", label: "Info" },
  { key: "warn", label: "Warn" },
  { key: "error", label: "Error" },
];

function levelTone(level: WidgetLogLevel): string {
  if (level === "error") return "text-danger";
  if (level === "warn") return "text-warning";
  return "text-text-muted";
}

function levelDot(level: WidgetLogLevel): string {
  if (level === "error") return "bg-danger";
  if (level === "warn") return "bg-warning";
  return "bg-text-muted/60";
}

function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 8 ? id.slice(0, 8) : id;
}

function fmtTime(ts: number): string {
  try {
    return new Date(ts).toLocaleTimeString();
  } catch {
    return String(ts);
  }
}

export function WidgetLogView() {
  const entries = useWidgetLogStore((s) => s.entries);
  const clear = useWidgetLogStore((s) => s.clear);

  const [filter, setFilter] = useState<WidgetLogLevel | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const pool = filter === "all" ? entries : entries.filter((e) => e.level === filter);
    return pool.slice().reverse(); // newest first
  }, [entries, filter]);

  const selected: WidgetLogEntry | null = useMemo(() => {
    if (!selectedId) return null;
    return filtered.find((e) => e.id === selectedId) ?? null;
  }, [filtered, selectedId]);

  return (
    <div className="flex-1 flex flex-col md:flex-row min-h-0 overflow-hidden">
      {/* Left column — filters + list */}
      <div className="flex flex-col w-full md:w-[340px] md:shrink-0 md:border-r md:border-surface-border md:min-h-0 max-h-[45vh] md:max-h-none">
        <div className="flex flex-col gap-2 px-3 py-2 bg-surface-raised">
          <div className="flex gap-1">
            {LEVELS.map((l) => (
              <button
                key={l.key}
                type="button"
                onClick={() => setFilter(l.key)}
                className={
                  "flex-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors " +
                  (filter === l.key
                    ? "border-accent/60 bg-accent/10 text-accent"
                    : "border-surface-border text-text-muted hover:bg-surface-overlay")
                }
              >
                {l.label}
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between text-[11px] text-text-muted">
            <span>
              {filtered.length} {filtered.length === 1 ? "entry" : "entries"}
              {entries.length !== filtered.length ? ` of ${entries.length}` : ""}
            </span>
            <button
              type="button"
              onClick={() => {
                clear();
                setSelectedId(null);
              }}
              disabled={entries.length === 0}
              className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-[11px] text-text-muted hover:bg-surface-overlay disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Trash2 className="h-3 w-3" />
              Clear
            </button>
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="px-3 py-8 text-center text-[12px] text-text-muted">
              {entries.length === 0
                ? "No widget logs yet. A pinned widget calling spindrel.log.info(...) will appear here."
                : "No entries at this level."}
            </div>
          ) : (
            <ul className="divide-y divide-surface-border">
              {filtered.map((e) => {
                const isSelected = e.id === selectedId;
                return (
                  <li key={e.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(e.id)}
                      className={
                        "w-full text-left px-3 py-2 flex gap-2 items-start hover:bg-surface-overlay " +
                        (isSelected ? "bg-accent/10" : "")
                      }
                    >
                      <span className={"mt-1 h-2 w-2 rounded-full shrink-0 " + levelDot(e.level)} />
                      <div className="flex-1 min-w-0">
                        <div className="flex justify-between gap-2 text-[11px] text-text-muted">
                          <span className={levelTone(e.level) + " uppercase tracking-wider"}>
                            {e.level}
                          </span>
                          <span className="tabular-nums">{formatRelativeTime(new Date(e.ts).toISOString())}</span>
                        </div>
                        <div className="text-[12px] text-text-strong truncate">{e.message || "(empty)"}</div>
                        <div className="text-[11px] text-text-muted truncate">
                          {e.botName || shortId(e.botId)}
                          {e.channelId ? " · ch " + shortId(e.channelId) : ""}
                          {e.pinId ? " · pin " + shortId(e.pinId) : ""}
                        </div>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      {/* Right column — detail */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {selected ? (
          <div className="p-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <span className={"h-2 w-2 rounded-full " + levelDot(selected.level)} />
              <span className={"text-[11px] uppercase tracking-wider " + levelTone(selected.level)}>
                {selected.level}
              </span>
              <span className="text-[11px] text-text-muted tabular-nums">
                {fmtTime(selected.ts)}
              </span>
            </div>
            <pre className="whitespace-pre-wrap break-words text-[12px] leading-relaxed rounded-md border border-surface-border bg-surface-raised p-3 text-text-strong">
              {selected.message || "(empty)"}
            </pre>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-[12px]">
              <dt className="text-text-muted">Bot</dt>
              <dd className="text-text-strong">
                {selected.botName || "—"}
                {selected.botId ? (
                  <span className="text-text-muted ml-1">({shortId(selected.botId)})</span>
                ) : null}
              </dd>
              <dt className="text-text-muted">Channel</dt>
              <dd className="text-text-strong">{selected.channelId ?? "—"}</dd>
              <dt className="text-text-muted">Pin</dt>
              <dd className="text-text-strong">{selected.pinId ?? "—"}</dd>
              <dt className="text-text-muted">Widget path</dt>
              <dd className="text-text-strong break-all">{selected.widgetPath ?? "—"}</dd>
              <dt className="text-text-muted">Timestamp</dt>
              <dd className="text-text-strong tabular-nums">
                {new Date(selected.ts).toISOString()}
              </dd>
            </dl>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center p-8 text-[12px] text-text-muted">
            Select a log entry to see the full message and its context.
          </div>
        )}
      </div>
    </div>
  );
}
