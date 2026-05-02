import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { Activity, Clock3, Hash, LayoutDashboard, MessageSquare, Pin, Wrench } from "lucide-react";
import { PinnedToolWidget } from "@/app/(app)/channels/[channelId]/PinnedToolWidget";
import { useChannelSessionCatalog } from "@/src/api/hooks/useChannelSessions";
import { formatRelativeTime } from "@/src/utils/format";
import type { ChannelSessionCatalogItem } from "@/src/lib/channelSessionSurfaces";
import type {
  PinnedWidget,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";
import type { DashboardChrome } from "@/src/lib/dashboardGrid";

function asPinnedWidget(pin: WidgetDashboardPin): PinnedWidget {
  return {
    id: pin.id,
    tool_name: pin.tool_name,
    display_name: pin.display_label ?? pin.tool_name,
    bot_id: pin.source_bot_id ?? "",
    widget_instance_id: pin.widget_instance_id ?? null,
    envelope: pin.envelope,
    position: pin.position,
    pinned_at: pin.pinned_at ?? new Date().toISOString(),
    widget_contract: pin.widget_contract ?? null,
    config: pin.widget_config ?? {},
    widget_health: pin.widget_health ?? null,
  };
}

function sessionHref(channelId: string, session: ChannelSessionCatalogItem): string {
  const params = session.surface_kind === "scratch" ? "?scratch=true" : "";
  return `/channels/${channelId}/session/${session.session_id}${params}`;
}

function pinLabel(pin: WidgetDashboardPin): string {
  return pin.display_label ?? pin.envelope?.display_label ?? pin.tool_name;
}

interface Props {
  channelId: string;
  channelName?: string;
  pins: WidgetDashboardPin[];
  railCount: number;
  dashboardHealthLabel: string;
  chrome: DashboardChrome;
  highlightPinId: string | null;
  onAddArtifact: () => void;
  onOpenCanvas: () => void;
  onUnpin: (pinId: string) => Promise<void> | void;
  onEnvelopeUpdate: (pinId: string, envelope: ToolResultEnvelope) => void;
  onEditPin: (pinId: string) => void;
}

export function ChannelWorkbenchOverview({
  channelId,
  channelName,
  pins,
  railCount,
  dashboardHealthLabel,
  chrome,
  highlightPinId,
  onAddArtifact,
  onOpenCanvas,
  onUnpin,
  onEnvelopeUpdate,
  onEditPin,
}: Props) {
  const { data: sessions, isLoading } = useChannelSessionCatalog(channelId);
  const recentSessions = (sessions ?? [])
    .slice()
    .sort((a, b) => new Date(b.last_active).getTime() - new Date(a.last_active).getTime())
    .slice(0, 5);
  const previewPins = pins.slice(0, 4);

  return (
    <main className="mx-auto flex w-full max-w-[1480px] flex-col gap-5 px-4 py-4 sm:px-6 lg:px-8">
      <section className="rounded-md bg-surface-raised/65 px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/80">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-emphasis/10 text-emphasis">
                <Activity size={13} />
              </span>
              Channel workbench
            </div>
            <h1 className="mt-2 truncate text-[22px] font-semibold leading-tight text-text">
              #{channelName ?? "channel"}
            </h1>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-text-muted">
              <span>{pins.length} pinned artifact{pins.length === 1 ? "" : "s"}</span>
              <span>{railCount} in chat shelf</span>
              <span>{dashboardHealthLabel}</span>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <button
              type="button"
              onClick={onAddArtifact}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-accent px-3 text-[12px] font-semibold text-white transition-colors hover:bg-accent/90"
            >
              <Pin size={13} />
              Pin artifact
            </button>
            <button
              type="button"
              onClick={onOpenCanvas}
              disabled={pins.length === 0}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-surface-overlay/55 px-3 text-[12px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
            >
              <LayoutDashboard size={13} />
              Canvas
            </button>
          </div>
        </div>
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(360px,0.85fr)]">
        <section className="rounded-md bg-surface-raised/55 px-4 py-4 sm:px-5">
          <SectionHeader
            icon={<Clock3 size={13} />}
            label="Recent sessions"
            title="Latest work"
            meta={`${recentSessions.length || 0} shown`}
          />
          <div className="mt-3 space-y-1.5">
            {isLoading && (
              <>
                <div className="h-16 animate-pulse rounded-md bg-surface-overlay/35" />
                <div className="h-16 animate-pulse rounded-md bg-surface-overlay/25" />
              </>
            )}
            {!isLoading && recentSessions.length === 0 && (
              <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-4 py-8 text-center text-[12px] text-text-dim">
                No recent sessions yet.
              </div>
            )}
            {recentSessions.map((session) => (
              <Link
                key={`${session.surface_kind}:${session.session_id}`}
                to={sessionHref(channelId, session)}
                className="group grid grid-cols-[18px_minmax(0,1fr)] gap-3 rounded-md bg-surface-overlay/25 px-3 py-2.5 transition-colors hover:bg-surface-overlay/55"
              >
                <MessageSquare size={14} className="mt-0.5 text-text-dim group-hover:text-accent" />
                <div className="min-w-0">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-[13px] font-semibold text-text">
                      {session.label || session.summary || `Session ${session.session_id.slice(0, 8)}`}
                    </span>
                    {session.is_current && (
                      <span className="shrink-0 rounded-full bg-accent/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em] text-accent">
                        Current
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-text-dim">
                    <span>{session.surface_kind === "scratch" ? "Scratch" : "Session"}</span>
                    <span>{session.message_count} msgs</span>
                    <span>{session.section_count} sections</span>
                    <span>{formatRelativeTime(session.last_active)}</span>
                  </div>
                  {(session.preview || session.summary) && (
                    <p className="mt-1 truncate text-[12px] text-text-muted">
                      {session.preview || session.summary}
                    </p>
                  )}
                </div>
              </Link>
            ))}
          </div>
        </section>

        <section className="rounded-md bg-surface-raised/45 px-4 py-4 sm:px-5">
          <SectionHeader
            icon={<Wrench size={13} />}
            label="Pinned artifacts"
            title="Workbench shelf"
            meta={`${pins.length} total`}
          />
          {pins.length === 0 ? (
            <div className="mt-3 rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-4 py-8 text-center">
              <p className="text-[13px] font-medium text-text">Nothing pinned yet</p>
              <button
                type="button"
                onClick={onAddArtifact}
                className="mt-3 text-[12px] font-semibold text-accent hover:underline"
              >
                Pin the first artifact
              </button>
            </div>
          ) : (
            <div className="mt-3 grid gap-3 lg:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">
              {previewPins.map((pin) => (
                <div
                  key={pin.id}
                  data-pin-id={pin.id}
                  className={"min-h-[360px] min-w-0 rounded-md bg-surface-overlay/20 md:min-h-[420px] " + (highlightPinId === pin.id ? "pin-flash" : "")}
                >
                  <PinnedToolWidget
                    widget={asPinnedWidget(pin)}
                    scope={{ kind: "dashboard", channelId }}
                    onUnpin={onUnpin}
                    onEnvelopeUpdate={onEnvelopeUpdate}
                    editMode={false}
                    onEdit={() => onEditPin(pin.id)}
                    borderless={chrome.borderless}
                    hoverScrollbars={chrome.hoverScrollbars}
                    hideTitles={chrome.hideTitles}
                  />
                </div>
              ))}
            </div>
          )}
          {pins.length > previewPins.length && (
            <button
              type="button"
              onClick={onOpenCanvas}
              className="mt-3 text-[12px] font-semibold text-accent hover:underline"
            >
              Open canvas for {pins.length - previewPins.length} more
            </button>
          )}
          {pins.length > 0 && (
            <div className="mt-4 space-y-1.5">
              {pins.slice(0, 6).map((pin) => (
                <button
                  type="button"
                  key={`row:${pin.id}`}
                  onClick={() => onEditPin(pin.id)}
                  className="grid w-full grid-cols-[18px_minmax(0,1fr)] gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-surface-overlay/55"
                >
                  <Hash size={13} className="mt-0.5 text-text-dim" />
                  <span className="truncate text-[12px] text-text-muted">{pinLabel(pin)}</span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function SectionHeader({
  icon,
  label,
  title,
  meta,
}: {
  icon: ReactNode;
  label: string;
  title: string;
  meta?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/75">
          <span className="flex h-5 w-5 items-center justify-center rounded-md bg-surface-overlay/55 text-text-dim">
            {icon}
          </span>
          {label}
        </div>
        <h2 className="mt-1 truncate text-[15px] font-semibold text-text">{title}</h2>
      </div>
      {meta && <span className="shrink-0 text-[11px] text-text-dim">{meta}</span>}
    </div>
  );
}
