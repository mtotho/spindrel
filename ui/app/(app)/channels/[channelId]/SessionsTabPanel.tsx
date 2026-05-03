import { useCallback, useMemo } from "react";
import { useMatch, useNavigate, useSearchParams } from "react-router-dom";
import { FolderOpen, MessageCircle, Plus } from "lucide-react";
import {
  useChannelSessionCatalog,
  useResetScratchSession,
} from "@/src/api/hooks/useChannelSessions";
import { useProjectChannels } from "@/src/api/hooks/useProjects";
import {
  getChannelSessionMeta,
  type ChannelSessionCatalogItem,
  type ChannelSessionSurface,
} from "@/src/lib/channelSessionSurfaces";
import type { ProjectSummary } from "@/src/types/api";

interface SessionsTabPanelProps {
  channelId: string;
  botId?: string;
  channelLabel?: string | null;
  project?: ProjectSummary | null;
  selectedSessionId?: string | null;
  onActivateSurface?: (surface: ChannelSessionSurface) => void;
}

export function SessionsTabPanel({
  channelId,
  botId,
  channelLabel,
  project,
  selectedSessionId,
  onActivateSurface,
}: SessionsTabPanelProps) {
  const navigate = useNavigate();
  const routeSessionMatch = useMatch("/channels/:channelId/session/:sessionId");
  const routeSessionId = routeSessionMatch?.params.sessionId ?? null;
  const [searchParams] = useSearchParams();
  const routeIsScratch = searchParams.get("scratch") === "true";
  const effectiveSelectedSessionId = selectedSessionId === undefined ? routeSessionId : selectedSessionId;
  const useRouteScratchKind = selectedSessionId === undefined;
  const { data: catalog, isLoading } = useChannelSessionCatalog(channelId);
  const resetScratch = useResetScratchSession();
  const { data: projectChannels } = useProjectChannels(project?.id);

  const { primaryRow, channelRows, scratchRows } = useMemo(() => {
    const items = catalog ?? [];
    const primary = items.find(
      (s) => s.surface_kind === "channel" && s.is_active,
    );
    return {
      primaryRow: primary ?? null,
      channelRows: items.filter(
        (s) => s.surface_kind === "channel" && s !== primary,
      ),
      scratchRows: items.filter((s) => s.surface_kind === "scratch"),
    };
  }, [catalog]);

  const activate = useCallback(
    (surface: ChannelSessionSurface) => {
      if (onActivateSurface) {
        onActivateSurface(surface);
        return;
      }
      if (surface.kind === "primary") {
        navigate(`/channels/${encodeURIComponent(channelId)}`);
      } else {
        navigate(
          `/channels/${encodeURIComponent(channelId)}/session/${encodeURIComponent(surface.sessionId)}` +
            (surface.kind === "scratch" ? "?scratch=true" : ""),
        );
      }
    },
    [channelId, navigate, onActivateSurface],
  );

  const handleCreate = useCallback(async () => {
    if (!botId) return;
    const next = await resetScratch.mutateAsync({
      parent_channel_id: channelId,
      bot_id: botId,
    });
    activate({ kind: "scratch", sessionId: next.session_id });
  }, [activate, botId, channelId, resetScratch]);

  const siblings = useMemo(
    () => (projectChannels ?? []).filter((row) => row.id !== channelId),
    [projectChannels, channelId],
  );

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="px-3 pb-2 pt-2">
        <button
          type="button"
          onClick={handleCreate}
          disabled={!botId || resetScratch.isPending}
          className="inline-flex h-8 w-full items-center justify-start gap-1.5 rounded-md bg-surface-raised/55 px-2.5 text-[12px] font-medium text-accent transition-colors hover:bg-surface-overlay disabled:opacity-40"
        >
          <Plus size={14} />
          New session
        </button>
      </div>

      <div className="scroll-subtle min-h-0 flex-1 overflow-y-auto px-2 pb-3 pt-0.5">
        {project && (
          <section className="mb-4 flex flex-col gap-2">
            <div className="flex items-baseline gap-2 px-1">
              <h3 className="text-[10px] font-semibold uppercase tracking-wider text-text-dim">
                In project
              </h3>
              <span className="truncate text-[10px] text-text-muted">
                {project.name}
              </span>
            </div>
            {siblings.length === 0 ? (
              <div className="mx-1 rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-3 py-4 text-center text-[11px] text-text-muted">
                No other channels in this project yet.
              </div>
            ) : (
              <div className="flex flex-col gap-1">
                {siblings.map((sibling) => (
                  <button
                    key={sibling.id}
                    type="button"
                    onClick={() =>
                      navigate(`/channels/${encodeURIComponent(sibling.id)}`)
                    }
                    className="mx-1 flex items-center gap-2 rounded-md bg-surface-raised/70 px-3 py-2 text-left transition-colors hover:bg-surface-overlay/55"
                  >
                    <FolderOpen size={13} className="shrink-0 text-text-dim" />
                    <span className="min-w-0 flex-1 truncate text-[12px] text-text">
                      {sibling.name}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
        )}

        <div className="flex flex-col gap-1.5">
          {primaryRow && (
            <SessionRow
              row={primaryRow}
              isPrimary
              isCurrent={effectiveSelectedSessionId == null}
              label={channelLabel ?? "Main chat"}
              onClick={() => activate({ kind: "primary" })}
            />
          )}
          {channelRows.map((row) => (
            <SessionRow
              key={row.session_id}
              row={row}
              isCurrent={
                effectiveSelectedSessionId
                  ? row.session_id === effectiveSelectedSessionId && (!useRouteScratchKind || !routeIsScratch)
                  : row.is_current
              }
              onClick={() =>
                activate({ kind: "channel", sessionId: row.session_id })
              }
            />
          ))}
          {scratchRows.map((row) => (
            <SessionRow
              key={row.session_id}
              row={row}
              isCurrent={
                effectiveSelectedSessionId
                  ? row.session_id === effectiveSelectedSessionId && (!useRouteScratchKind || routeIsScratch)
                  : row.is_current
              }
              onClick={() =>
                activate({ kind: "scratch", sessionId: row.session_id })
              }
            />
          ))}
          {!isLoading &&
            !primaryRow &&
            channelRows.length === 0 &&
            scratchRows.length === 0 && (
              <div className="mx-1 rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-4 py-8 text-center">
                <MessageCircle size={18} className="mx-auto mb-2 text-text-dim/70" />
                <div className="text-[12px] text-text-muted">No sessions yet</div>
                <button
                  type="button"
                  onClick={handleCreate}
                  disabled={!botId || resetScratch.isPending}
                  className="mt-3 inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] text-accent hover:bg-surface-overlay disabled:opacity-40"
                >
                  <Plus size={13} />
                  Start a new session
                </button>
              </div>
            )}
        </div>
      </div>
    </div>
  );
}

function SessionRow({
  row,
  isPrimary = false,
  isCurrent,
  label,
  onClick,
}: {
  row: ChannelSessionCatalogItem;
  isPrimary?: boolean;
  isCurrent: boolean;
  label?: string;
  onClick: () => void;
}) {
  const title = label ?? ((row.label?.trim() || (isPrimary ? "Main chat" : "Untitled session")));
  const meta = getChannelSessionMeta(row);
  const detailLine = row.preview ? `${meta} · ${row.preview}` : meta;
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative mx-1 rounded-md px-3 py-2.5 text-left transition-colors ${
        isCurrent
          ? "bg-accent/[0.08] text-text before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[3px] before:-translate-y-1/2 before:rounded-full before:bg-accent"
          : "bg-surface-raised/70 text-text hover:bg-surface-overlay/55"
      }`}
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <div
          className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${
            isPrimary ? "bg-accent/[0.08] text-accent" : "bg-surface-overlay/65 text-text-dim"
          }`}
        >
          <MessageCircle size={13} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-1.5">
            <span className="min-w-0 truncate text-[13px] font-medium leading-5">
              {title}
            </span>
            {isPrimary && (
              <span className="shrink-0 rounded-full bg-surface-overlay px-1.5 py-0.5 text-[9px] uppercase tracking-[0.08em] text-text-dim">
                Primary
              </span>
            )}
          </div>
          <div className="mt-0.5 truncate text-[11px] leading-4 text-text-muted">
            {detailLine}
          </div>
        </div>
      </div>
    </button>
  );
}
