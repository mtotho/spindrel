import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Brain, ExternalLink, FileText, Search, Sparkles, X } from "lucide-react";
import {
  type LearningSearchResult,
  type MemoryFileActivity,
  type MemoryObservatoryFile,
  useLearningSearch,
  useMemoryObservatory,
} from "../../api/hooks/useLearningOverview";
import { ActionButton, EmptyState, QuietPill } from "../shared/SettingsControls";
import { SourceFileInspector } from "../shared/SourceFileInspector";
import type { LensTransform } from "./spatialGeometry";
import {
  buildObservatoryEventMarks,
  buildObservatoryLanes,
  memoryFileKey,
} from "./memoryObservatoryLayout";

export type MemoryObservationSelection =
  | { kind: "event"; event: MemoryFileActivity }
  | { kind: "file"; file: MemoryObservatoryFile }
  | { kind: "search"; result: LearningSearchResult };

interface MemoryObservatoryProps {
  zoom: number;
  lens?: LensTransform | null;
  onInspect: (selection: MemoryObservationSelection) => void;
}

const W = 980;
const H = 680;
const FAR_THRESHOLD = 0.28;
const MID_THRESHOLD = 0.72;

function fmtRelative(value?: string | null) {
  if (!value) return "never";
  const diff = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(diff)) return "unknown";
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function sourceTitle(selection: MemoryObservationSelection) {
  if (selection.kind === "search") return selection.result.title;
  if (selection.kind === "file") return selection.file.file_path;
  return selection.event.file_path;
}

function selectionSourceFile(selection: MemoryObservationSelection) {
  if (selection.kind === "search") return selection.result.source_file ?? null;
  if (selection.kind === "file") return selection.file.source_file ?? null;
  return selection.event.source_file ?? null;
}

function selectionFallback(selection: MemoryObservationSelection) {
  if (selection.kind === "search") return selection.result.open_url ?? "/admin/learning#Memory";
  if (selection.kind === "file") return `/admin/bots/${encodeURIComponent(selection.file.bot_id)}#learning`;
  return selection.event.bot_id ? `/admin/bots/${encodeURIComponent(selection.event.bot_id)}#learning` : "/admin/learning#Memory";
}

export function MemoryObservationPanel({
  selection,
  onClose,
}: {
  selection: MemoryObservationSelection | null;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  if (!selection) return null;

  const sourceFile = selectionSourceFile(selection);
  const fallback = selectionFallback(selection);
  if (sourceFile) {
    return (
      <div
        className="absolute bottom-4 right-4 z-[4] w-[min(520px,calc(100vw-2rem))] max-h-[min(720px,calc(100vh-2rem))]"
        onPointerDown={(e) => e.stopPropagation()}
      >
        <SourceFileInspector
          variant="panel"
          target={sourceFile}
          title={sourceTitle(selection)}
          subtitle={selection.kind === "event" ? `${selection.event.operation} by ${selection.event.bot_name}` : undefined}
          fallbackUrl={fallback}
          onOpenFallback={(url) => navigate(url)}
          onClose={onClose}
          className="h-[min(720px,calc(100vh-2rem))]"
        />
      </div>
    );
  }

  const botName =
    selection.kind === "search"
      ? selection.result.bot_name
      : selection.kind === "file"
      ? selection.file.bot_name
      : selection.event.bot_name;
  const meta =
    selection.kind === "event"
      ? [
          selection.event.operation,
          selection.event.job_type?.replace("_", " "),
          fmtRelative(selection.event.created_at),
        ].filter(Boolean).join(" · ")
      : selection.kind === "file"
      ? [`${selection.file.write_count} writes`, `${selection.file.hygiene_count} hygiene`, fmtRelative(selection.file.last_updated_at)].join(" · ")
      : [selection.result.source, selection.result.score != null ? `score ${selection.result.score.toFixed(2)}` : null].filter(Boolean).join(" · ");

  return (
    <aside
      className="absolute bottom-4 right-4 z-[4] flex w-[min(420px,calc(100vw-2rem))] flex-col gap-3 rounded-md bg-surface-raised/95 p-4 text-sm shadow-lg ring-1 ring-surface-border"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-1.5">
            <QuietPill label="memory" />
            {botName && <span className="truncate text-[11px] text-text-dim">{botName}</span>}
          </div>
          <h3 className="truncate text-[14px] font-semibold text-text">{sourceTitle(selection)}</h3>
          <p className="mt-1 text-[12px] text-text-dim">{meta}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-[32px] min-w-[32px] items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay/60 hover:text-text"
          aria-label="Close memory detail"
        >
          <X size={15} />
        </button>
      </div>
      {selection.kind === "search" && selection.result.snippet && (
        <p className="line-clamp-4 text-[12px] leading-relaxed text-text-muted">{selection.result.snippet}</p>
      )}
      <div>
        <ActionButton
          label="Open Memory Center"
          size="small"
          variant="secondary"
          icon={<ExternalLink size={13} />}
          onPress={() => navigate(fallback)}
        />
      </div>
    </aside>
  );
}

export function MemoryObservatory({ zoom, lens = null, onInspect }: MemoryObservatoryProps) {
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [query, setQuery] = useState("");
  const observatory = useMemoryObservatory(days);
  const search = useLearningSearch();

  const data = observatory.data;
  const maxWriteCount = Math.max(1, ...(data?.hot_files.map((file) => file.write_count) ?? [1]));
  const lanes = useMemo(
    () => buildObservatoryLanes(data?.bots ?? [], maxWriteCount),
    [data?.bots, maxWriteCount],
  );
  const eventMarks = useMemo(
    () => buildObservatoryEventMarks(data?.recent_events ?? [], lanes),
    [data?.recent_events, lanes],
  );
  const matchedKeys = useMemo(() => {
    const results = search.data?.results ?? [];
    return new Set(results.map((result) => memoryFileKey(result.bot_id, result.file_path)));
  }, [search.data?.results]);
  const accessDenied = observatory.error != null && !data;

  const runSearch = () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    search.mutate({
      query: trimmed,
      sources: ["memory"],
      days,
      top_k_per_source: 10,
    });
  };

  const showMid = zoom >= FAR_THRESHOLD;
  const showClose = zoom >= MID_THRESHOLD;
  const effectiveOpacity = observatory.error ? 0.55 : 1;

  return (
    <div
      className="absolute pointer-events-auto"
      data-tile-kind="memory-observatory"
      style={{
        left: -W / 2,
        top: -H / 2,
        width: W,
        height: H,
        transform: lens ? `translate(${lens.dxWorld}px, ${lens.dyWorld}px) scale(${lens.sizeFactor})` : undefined,
        transformOrigin: "center center",
        opacity: effectiveOpacity,
      }}
      title="Memory Observatory"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <svg width={W} height={H} viewBox={`${-W / 2} ${-H / 2} ${W} ${H}`} className="absolute inset-0 overflow-visible">
        <defs>
          <radialGradient id="memory-observatory-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgb(var(--color-purple))" stopOpacity="0.22" />
            <stop offset="48%" stopColor="rgb(var(--color-accent))" stopOpacity="0.08" />
            <stop offset="100%" stopColor="rgb(var(--color-purple))" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="0" cy="0" rx="250" ry="125" fill="url(#memory-observatory-core)" />
        <ellipse cx="0" cy="0" rx="118" ry="58" fill="none" stroke="rgb(var(--color-purple) / 0.35)" strokeWidth="1.3" strokeDasharray="7 9" />
        <circle cx="0" cy="0" r="26" fill="rgb(var(--color-purple) / 0.18)" stroke="rgb(var(--color-purple) / 0.55)" strokeWidth="1.2" />
        {showMid && lanes.map((lane) => (
          <g key={lane.bot.bot_id}>
            <ellipse
              cx="0"
              cy="0"
              rx={lane.rx}
              ry={lane.ry}
              fill="none"
              stroke={lane.color}
              strokeOpacity={0.15}
              strokeWidth={1}
              strokeDasharray="4 10"
            />
            {lane.files.map((mark) => {
              const matched = matchedKeys.has(memoryFileKey(mark.file.bot_id, mark.file.file_path));
              return (
                <circle
                  key={mark.file.id}
                  cx={mark.x}
                  cy={mark.y}
                  r={mark.r}
                  fill={mark.color}
                  fillOpacity={matched ? 0.75 : 0.28}
                  stroke={mark.color}
                  strokeOpacity={matched ? 0.95 : 0.42}
                  strokeWidth={matched ? 2.2 : 1}
                  style={{ cursor: "pointer" }}
                  onClick={() => onInspect({ kind: "file", file: mark.file })}
                />
              );
            })}
          </g>
        ))}
        {showMid && eventMarks.map((mark, index) => {
          const matched = matchedKeys.has(mark.matchKey);
          return (
            <g key={`${mark.event.correlation_id ?? mark.event.created_at}:${mark.event.file_path}:${index}`}>
              {mark.event.is_hygiene && (
                <circle cx={mark.x} cy={mark.y} r={mark.r + 5} fill="none" stroke={mark.color} strokeOpacity={matched ? 0.9 : 0.36} strokeWidth="1" />
              )}
              <circle
                cx={mark.x}
                cy={mark.y}
                r={matched ? mark.r + 2 : mark.r}
                fill={mark.color}
                fillOpacity={matched ? 0.95 : 0.72}
                style={{ cursor: "pointer" }}
                onClick={() => onInspect({ kind: "event", event: mark.event })}
              />
            </g>
          );
        })}
      </svg>

      <div className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-surface-raised/80 text-purple ring-1 ring-purple/30 backdrop-blur">
          <Brain size={24} />
        </div>
        <div className="mt-2 rounded-md bg-surface-raised/75 px-3 py-1.5 text-[12px] font-semibold text-text shadow-sm ring-1 ring-surface-border/70 backdrop-blur">
          Memory Observatory
        </div>
        <div className="mt-1 flex items-center gap-1.5 rounded-full bg-surface-raised/60 px-2 py-1 text-[10px] text-text-dim ring-1 ring-surface-border/60">
          <Sparkles size={10} />
          <span>{accessDenied ? "admin only" : `${data?.total_writes ?? 0} writes · ${data?.active_bot_count ?? 0} bots`}</span>
        </div>
      </div>

      {showMid && lanes.map((lane) => (
        <button
          key={lane.bot.bot_id}
          type="button"
          className="absolute max-w-[160px] truncate rounded-full bg-surface-raised/70 px-2 py-1 text-[10px] font-medium text-text-muted ring-1 ring-surface-border/60 backdrop-blur hover:text-text"
          style={{
            left: W / 2 + Math.cos(lane.angle) * (lane.rx + 72) - 80,
            top: H / 2 + Math.sin(lane.angle) * (lane.ry + 36) - 12,
          }}
          onClick={() => navigate(`/admin/bots/${encodeURIComponent(lane.bot.bot_id)}#learning`)}
          title={`${lane.bot.bot_name} · ${lane.bot.write_count} writes`}
        >
          {lane.bot.bot_name} · {lane.bot.write_count}
        </button>
      ))}

      {showClose && !accessDenied && (
        <div className="absolute left-1/2 top-[calc(50%+92px)] flex w-[430px] -translate-x-1/2 flex-col gap-2 rounded-md bg-surface-raised/88 p-3 text-[12px] text-text-muted shadow-lg ring-1 ring-surface-border backdrop-blur">
          <div className="flex items-center gap-2">
            <div className="flex min-h-[34px] flex-1 items-center gap-2 rounded-md bg-input px-2.5 text-text-dim focus-within:ring-2 focus-within:ring-accent/25">
              <Search size={13} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") runSearch();
                }}
                placeholder="Search memory..."
                className="min-w-0 flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
              />
            </div>
            <ActionButton label={search.isPending ? "Searching" : "Search"} size="small" disabled={!query.trim() || search.isPending} onPress={runSearch} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex gap-1">
              {[1, 7, 30, 0].map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setDays(value)}
                  className={`rounded-md px-2 py-1 text-[11px] font-semibold ${days === value ? "bg-accent/[0.10] text-accent" : "text-text-dim hover:bg-surface-overlay/60 hover:text-text-muted"}`}
                >
                  {value === 0 ? "All" : value === 1 ? "24h" : `${value}d`}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => navigate("/admin/learning#Memory")}
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-semibold text-accent hover:bg-accent/[0.08]"
            >
              Memory Center <ExternalLink size={11} />
            </button>
          </div>
          {search.data?.results?.length ? (
            <div className="max-h-44 overflow-auto">
              {search.data.results.slice(0, 5).map((result) => (
                <button
                  key={result.id}
                  type="button"
                  onClick={() => onInspect({ kind: "search", result })}
                  className="flex w-full min-w-0 items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-surface-overlay/50"
                >
                  <FileText size={13} className="mt-0.5 shrink-0 text-text-dim" />
                  <span className="min-w-0">
                    <span className="block truncate text-[12px] font-medium text-text">{result.title}</span>
                    <span className="line-clamp-1 text-[11px] text-text-dim">{result.snippet || fmtRelative(result.created_at)}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : observatory.isLoading ? (
            <div className="h-10 rounded-md bg-surface-overlay/35" />
          ) : data?.recent_events.length === 0 ? (
            <EmptyState message="No memory writes in this window." />
          ) : (
            <div className="line-clamp-2 text-[11px] text-text-dim">
              Hot files grow with repeated writes. Ringed sparks came from memory hygiene or skill review runs.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
