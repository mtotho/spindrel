import { useEffect, useMemo, useState } from "react";
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
  observatoryHorizonDays,
  temporalLaneScale,
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

const W = 1240;
const H = 920;
const FAR_THRESHOLD = 0.28;
const MID_THRESHOLD = 0.72;
const DETAIL_THRESHOLD = 1.15;

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

function displayFileName(path: string) {
  return path.split("/").filter(Boolean).pop() ?? path;
}

function detailWorldSize(zoom: number, screenPx: number, minScreenPx = 0) {
  return Math.max(minScreenPx, screenPx) / Math.max(zoom, 0.1);
}

function fileMarkKey(file: MemoryObservatoryFile) {
  return memoryFileKey(file.bot_id, file.file_path);
}

function eventMarkKey(event: MemoryFileActivity, index: number) {
  return `event:${event.correlation_id ?? event.created_at}:${event.file_path}:${index}`;
}

export function MemoryObservationPanel({
  selection,
  onClose,
}: {
  selection: MemoryObservationSelection | null;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    setExpanded(false);
  }, [selection]);
  if (!selection) return null;

  const sourceFile = selectionSourceFile(selection);
  const fallback = selectionFallback(selection);
  if (sourceFile) {
    return (
      <div
        className={`absolute bottom-4 right-4 z-[4] max-h-[min(720px,calc(100vh-2rem))] transition-[width] duration-200 ${
          expanded ? "w-[min(920px,calc(100vw-2rem))]" : "w-[min(520px,calc(100vw-2rem))]"
        }`}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <SourceFileInspector
          variant="panel"
          target={sourceFile}
          title={sourceTitle(selection)}
          subtitle={selection.kind === "event" ? `${selection.event.operation} by ${selection.event.bot_name}` : undefined}
          fallbackUrl={fallback}
          onOpenFallback={(url) => navigate(url)}
          onShowSource={() => setExpanded(true)}
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
  const [hoveredMarkKey, setHoveredMarkKey] = useState<string | null>(null);
  const observatory = useMemoryObservatory(days);
  const search = useLearningSearch();

  const data = observatory.data;
  const horizonDays = observatoryHorizonDays(days);
  const maxWriteCount = Math.max(1, ...(data?.hot_files.map((file) => file.write_count) ?? [1]));
  const lanes = useMemo(
    () => buildObservatoryLanes(data?.bots ?? [], maxWriteCount, horizonDays),
    [data?.bots, maxWriteCount, horizonDays],
  );
  const eventMarks = useMemo(
    () => buildObservatoryEventMarks(data?.recent_events ?? [], lanes, horizonDays),
    [data?.recent_events, lanes, horizonDays],
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
  const showDetail = zoom >= DETAIL_THRESHOLD;
  const showRichDetail = zoom >= 2.1;
  const detailLabelSize = detailWorldSize(zoom, 12);
  const detailMetaSize = detailWorldSize(zoom, 10);
  const detailGap = detailWorldSize(zoom, 8);
  const maxLaneRx = Math.max(250, ...lanes.map((lane) => lane.rx));
  const maxLaneRy = Math.max(122, ...lanes.map((lane) => lane.ry));
  const temporalRings = [
    { days: 1, label: "24h" },
    { days: 7, label: "7d" },
    { days: 30, label: "30d" },
    { days: 90, label: "90d+" },
  ].filter((ring) => horizonDays >= ring.days || (days === 0 && ring.days <= 90));
  const effectiveOpacity = observatory.error ? 0.55 : 1;

  return (
    <div
      className="absolute pointer-events-none"
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
    >
      <svg width={W} height={H} viewBox={`${-W / 2} ${-H / 2} ${W} ${H}`} className="absolute inset-0 overflow-visible pointer-events-none">
        <defs>
          <radialGradient id="memory-observatory-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="rgb(var(--color-purple))" stopOpacity="0.22" />
            <stop offset="48%" stopColor="rgb(var(--color-accent))" stopOpacity="0.08" />
            <stop offset="100%" stopColor="rgb(var(--color-purple))" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="0" cy="0" rx="330" ry="162" fill="url(#memory-observatory-core)" />
        <ellipse cx="0" cy="0" rx="155" ry="74" fill="none" stroke="rgb(var(--color-purple) / 0.35)" strokeWidth="1.3" strokeDasharray="7 9" />
        {showMid && temporalRings.map((ring) => {
          const ageFactor = Math.min(1, ring.days / horizonDays);
          const scale = temporalLaneScale(ageFactor);
          const rx = maxLaneRx * scale;
          const ry = maxLaneRy * scale;
          return (
            <g key={ring.label}>
              <ellipse
                cx="0"
                cy="0"
                rx={rx}
                ry={ry}
                fill="none"
                stroke="rgb(var(--color-text-dim))"
                strokeOpacity={0.11}
                strokeWidth={0.9}
                strokeDasharray="3 12"
              />
              {showRichDetail && (
                <text
                  x={rx + detailGap}
                  y={detailMetaSize * 0.4}
                  fill="rgb(var(--color-text-dim))"
                  fillOpacity={0.48}
                  fontSize={detailMetaSize}
                  paintOrder="stroke"
                  stroke="rgb(var(--color-surface-base))"
                  strokeOpacity={0.72}
                  strokeWidth={detailWorldSize(zoom, 2, 0.9)}
                >
                  {ring.label}
                </text>
              )}
            </g>
          );
        })}
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
              const markKey = fileMarkKey(mark.file);
              const matched = matchedKeys.has(markKey);
              const hovered = hoveredMarkKey === markKey;
              const prominent = mark.rank === 0 || mark.file.write_count >= 4 || mark.file.hygiene_count >= 2 || matched;
              const showLabel = showRichDetail && (prominent || hovered);
              const markerRadius = showDetail
                ? Math.max(detailWorldSize(zoom, 10), Math.min(detailWorldSize(zoom, hovered || prominent ? 28 : 20), mark.r * 0.4))
                : mark.r;
              const labelX = mark.x + markerRadius + detailGap;
              const labelY = mark.y - detailGap * 0.25;
              return (
                <g
                  key={mark.file.id}
                  className="pointer-events-auto"
                  style={{ cursor: "pointer" }}
                  onPointerDown={(event) => event.stopPropagation()}
                  onMouseEnter={() => setHoveredMarkKey(markKey)}
                  onMouseLeave={() => setHoveredMarkKey((current) => current === markKey ? null : current)}
                  onClick={() => onInspect({ kind: "file", file: mark.file })}
                >
                  <title>{`${mark.file.file_path} · ${mark.file.write_count} writes`}</title>
                  <circle
                    cx={mark.x}
                    cy={mark.y}
                    r={markerRadius}
                    fill={mark.color}
                    fillOpacity={matched ? 0.75 : showDetail ? 0.38 : 0.28}
                    stroke={mark.color}
                    strokeOpacity={matched ? 0.95 : showDetail ? 0.62 : 0.42}
                    strokeWidth={detailWorldSize(zoom, matched ? 2.2 : hovered ? 2 : 1.4)}
                  />
                  {showLabel && (
                    <>
                      <text
                        x={labelX}
                        y={labelY}
                        fill="rgb(var(--color-text))"
                        fillOpacity={hovered || matched ? 0.98 : 0.78}
                        fontSize={detailLabelSize}
                        fontWeight={650}
                        paintOrder="stroke"
                        stroke="rgb(var(--color-surface-base))"
                        strokeOpacity={0.82}
                        strokeWidth={detailWorldSize(zoom, 3)}
                      >
                        {displayFileName(mark.file.file_path)}
                      </text>
                      <text
                        x={labelX}
                        y={labelY + detailLabelSize + detailWorldSize(zoom, 2, 1)}
                        fill="rgb(var(--color-text-muted))"
                        fillOpacity={hovered || matched ? 0.78 : 0.58}
                        fontSize={detailMetaSize}
                        paintOrder="stroke"
                        stroke="rgb(var(--color-surface-base))"
                        strokeOpacity={0.82}
                        strokeWidth={detailWorldSize(zoom, 2.4)}
                      >
                        {mark.file.write_count} writes · {fmtRelative(mark.file.last_updated_at)}
                      </text>
                    </>
                  )}
                </g>
              );
            })}
          </g>
        ))}
        {showMid && eventMarks.map((mark, index) => {
          const matched = matchedKeys.has(mark.matchKey);
          const markKey = eventMarkKey(mark.event, index);
          const hovered = hoveredMarkKey === markKey;
          const eventRadius = showDetail
            ? detailWorldSize(zoom, hovered || matched ? 8 : mark.event.is_hygiene ? 6 : 4)
            : (matched ? mark.r + 2 : mark.r);
          return (
            <g
              key={`${mark.event.correlation_id ?? mark.event.created_at}:${mark.event.file_path}:${index}`}
              className="pointer-events-auto"
              style={{ cursor: "pointer" }}
              onPointerDown={(event) => event.stopPropagation()}
              onMouseEnter={() => setHoveredMarkKey(markKey)}
              onMouseLeave={() => setHoveredMarkKey((current) => current === markKey ? null : current)}
              onClick={() => onInspect({ kind: "event", event: mark.event })}
            >
              <title>{`${mark.event.operation} · ${mark.event.file_path}`}</title>
              {mark.event.is_hygiene && (
                <circle
                  cx={mark.x}
                  cy={mark.y}
                  r={eventRadius + detailWorldSize(zoom, 6)}
                  fill="none"
                  stroke={mark.color}
                  strokeOpacity={matched ? 0.9 : 0.36}
                  strokeWidth={detailWorldSize(zoom, 1.1)}
                />
              )}
              <circle
                cx={mark.x}
                cy={mark.y}
                r={eventRadius}
                fill={mark.color}
                fillOpacity={matched ? 0.95 : 0.72}
              />
              {showRichDetail && (hovered || matched) && (
                <text
                  x={mark.x + eventRadius + detailGap * 0.6}
                  y={mark.y + detailMetaSize * 0.35}
                  fill="rgb(var(--color-text-dim))"
                  fillOpacity={0.62}
                  fontSize={detailMetaSize}
                  paintOrder="stroke"
                  stroke="rgb(var(--color-surface-base))"
                  strokeOpacity={0.78}
                  strokeWidth={detailWorldSize(zoom, 2.2)}
                >
                  {mark.event.operation}
                </text>
              )}
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
          className="absolute max-w-[160px] truncate rounded-full bg-surface-raised/70 px-2 py-1 text-[10px] font-medium text-text-muted ring-1 ring-surface-border/60 backdrop-blur hover:text-text pointer-events-auto"
          style={{
            left: W / 2 + Math.cos(lane.angle) * (lane.rx + 90) - 80,
            top: H / 2 + Math.sin(lane.angle) * (lane.ry + 48) - 12,
          }}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={() => navigate(`/admin/bots/${encodeURIComponent(lane.bot.bot_id)}#learning`)}
          title={`${lane.bot.bot_name} · ${lane.bot.write_count} writes`}
        >
          {lane.bot.bot_name} · {lane.bot.write_count}
        </button>
      ))}

      {showClose && !accessDenied && (
        <div
          className="absolute left-1/2 top-[calc(50%+255px)] flex w-[520px] -translate-x-1/2 flex-col gap-2 rounded-md bg-surface-raised/88 p-3 text-[12px] text-text-muted shadow-lg ring-1 ring-surface-border backdrop-blur pointer-events-auto"
          onPointerDown={(e) => e.stopPropagation()}
        >
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
