import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Maximize2, Minus, MoreHorizontal, Rows3, X as CloseIcon } from "lucide-react";
import { ChatSession } from "@/src/components/chat/ChatSession";
import { useRenameSession } from "@/src/api/hooks/useChannelSessions";
import { useSessionHeaderStats } from "@/src/api/hooks/useSessionHeaderStats";
import {
  buildChannelSessionChatSource,
  buildScratchChatSource,
  formatScratchSessionTimestamp,
  resizeChannelChatPanes,
  type ChannelChatPane,
  type ChannelSessionCatalogItem,
} from "@/src/lib/channelSessionSurfaces";

interface ChannelChatPaneGroupProps {
  channelId: string;
  botId?: string | null;
  activeSessionId?: string | null;
  panes: ChannelChatPane[];
  widths: Record<string, number>;
  focusedPaneId: string | null;
  maximizedPaneId?: string | null;
  catalog?: ChannelSessionCatalogItem[] | null;
  primaryNode: ReactNode;
  emptyState?: ReactNode;
  chatMode?: "default" | "terminal";
  onFocusPane: (paneId: string) => void;
  onClosePane: (paneId: string) => void;
  onMaximizePane: (paneId: string) => void;
  onRestorePanes: () => void;
  onMinimizePane: (paneId: string) => void;
  onMovePane: (paneId: string, direction: "left" | "right") => void;
  onCommitPaneWidths: (widths: Record<string, number>) => void;
  onMakePrimary: (pane: ChannelChatPane) => void;
  onOpenSessions?: () => void;
  onOpenSessionSplit?: () => void;
  onToggleFocusLayout?: () => void;
}

function sessionIdForPane(pane: ChannelChatPane, activeSessionId?: string | null): string | null {
  if (pane.surface.kind === "primary") return activeSessionId ?? null;
  return pane.surface.sessionId;
}

function labelForPane(
  pane: ChannelChatPane,
  catalog: ChannelSessionCatalogItem[] | null | undefined,
): { title: string; meta: string | null; kind: string; primary: boolean } {
  const surface = pane.surface;
  if (surface.kind === "primary") {
    const row = catalog?.find((item) => item.is_active) ?? null;
    return {
      title: row?.label?.trim() || row?.summary?.trim() || row?.preview?.trim() || "Primary session",
      meta: row ? `${formatScratchSessionTimestamp(row.last_active)} · ${row.message_count} msgs · ${row.section_count} sections` : null,
      kind: "Primary",
      primary: true,
    };
  }
  const row = catalog?.find((item) => item.session_id === surface.sessionId) ?? null;
  const kind = surface.kind;
  return {
    title: row?.label?.trim() || row?.summary?.trim() || row?.preview?.trim() || "Untitled session",
    meta: row ? `${formatScratchSessionTimestamp(row.last_active)} · ${row.message_count} msgs · ${row.section_count} sections` : null,
    kind: kind === "scratch" ? "Scratch" : row?.is_active ? "Primary" : "Previous",
    primary: !!row?.is_active,
  };
}

function formatPaneTokens(value: number | null | undefined): string | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(Math.round(value));
}

function formatPaneContextStats(stats: ReturnType<typeof useSessionHeaderStats>["data"]): string | null {
  if (!stats) return null;
  const tokenBits = [
    formatPaneTokens(stats.currentPromptTokens ?? stats.grossPromptTokens ?? stats.consumedTokens),
    formatPaneTokens(stats.totalTokens),
  ];
  const bits = [
    tokenBits[0] && tokenBits[1] ? `${tokenBits[0]}/${tokenBits[1]}` : tokenBits[0],
    typeof stats.turnsInContext === "number" ? `${stats.turnsInContext} turns in ctx` : null,
    typeof stats.turnsUntilCompaction === "number" ? `${stats.turnsUntilCompaction} until compact` : null,
  ].filter(Boolean);
  return bits.length > 0 ? bits.join(" · ") : null;
}

function PaneHeader({
  pane,
  channelId,
  activeSessionId,
  catalog,
  focused,
  maximized,
  onClose,
  onMaximize,
  onRestore,
  onMinimize,
  onMoveLeft,
  onMoveRight,
  onMakePrimary,
  canMoveLeft,
  canMoveRight,
}: {
  pane: ChannelChatPane;
  channelId: string;
  activeSessionId?: string | null;
  catalog?: ChannelSessionCatalogItem[] | null;
  focused: boolean;
  maximized: boolean;
  onClose: () => void;
  onMaximize: () => void;
  onRestore: () => void;
  onMinimize: () => void;
  onMoveLeft: () => void;
  onMoveRight: () => void;
  onMakePrimary: () => void;
  canMoveLeft: boolean;
  canMoveRight: boolean;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState("");
  const rename = useRenameSession();
  const sessionId = sessionIdForPane(pane, activeSessionId);
  const { data: sessionStats } = useSessionHeaderStats(channelId, sessionId);
  const header = labelForPane(pane, catalog);
  const contextStats = formatPaneContextStats(sessionStats);
  const tooltip = [header.title, header.meta, contextStats].filter(Boolean).join(" · ");

  const commitRename = () => {
    if (!sessionId || !title.trim()) return;
    rename.mutate(
      { session_id: sessionId, title: title.trim(), parent_channel_id: channelId },
      {
        onSuccess: () => {
          setRenaming(false);
          setMenuOpen(false);
        },
      },
    );
  };

  return (
    <div className={`group/pane-header flex h-9 shrink-0 items-center gap-2 border-b border-surface-border/45 bg-surface px-3 ${focused ? "text-text" : "text-text-muted"}`}>
      <div className="min-w-0 flex-1">
        {renaming ? (
          <input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") commitRename();
              if (event.key === "Escape") setRenaming(false);
            }}
            className="h-7 w-full rounded-md border border-surface-border bg-surface px-2 text-[12px] text-text outline-none focus:border-accent"
          />
        ) : (
          <div className="flex min-w-0 items-center gap-2" title={tooltip}>
            <span className="min-w-0 max-w-[45%] truncate text-[12px] font-semibold text-text">{header.title}</span>
            <span className="shrink-0 text-[9px] uppercase tracking-[0.08em] text-text-dim">
              {header.kind}
            </span>
            {contextStats && (
              <span className="min-w-0 truncate text-[10px] text-text-dim">
                {contextStats}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <button
          type="button"
          onClick={onMinimize}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
          aria-label="Minimize to mini chat"
          title="Minimize to mini chat"
        >
          <Minus size={14} />
        </button>
        <button
          type="button"
          onClick={maximized ? onRestore : onMaximize}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
          aria-label={maximized ? "Restore splits" : "Maximize pane"}
          title={maximized ? "Restore splits" : "Maximize pane"}
        >
          {maximized ? <Rows3 size={13} /> : <Maximize2 size={13} />}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
          aria-label="Close pane"
          title="Close pane"
        >
          <CloseIcon size={13} />
        </button>
      </div>
      <div className="relative shrink-0">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            setMenuOpen((open) => !open);
          }}
          className="flex h-7 w-7 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
          aria-label="Session pane actions"
          title="More session actions"
        >
          <MoreHorizontal size={14} />
        </button>
        {menuOpen && (
          <div className="absolute right-0 top-8 z-20 w-48 rounded-md border border-surface-border bg-surface-raised p-1 shadow-lg">
            <div className="px-2 pb-1 pt-1 text-[10px] uppercase tracking-[0.08em] text-text-dim/70">Layout</div>
            <button
              type="button"
              onClick={() => {
                maximized ? onRestore() : onMaximize();
                setMenuOpen(false);
              }}
              className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
            >
              {maximized ? "Restore split layout" : "Maximize pane"}
            </button>
            <button
              type="button"
              onClick={() => {
                onMinimize();
                setMenuOpen(false);
              }}
              className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
            >
              Minimize to mini chat
            </button>
            <button
              type="button"
              disabled={!canMoveLeft}
              onClick={() => {
                onMoveLeft();
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:opacity-40"
            >
              <ArrowLeft size={12} />
              Move left
            </button>
            <button
              type="button"
              disabled={!canMoveRight}
              onClick={() => {
                onMoveRight();
                setMenuOpen(false);
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:opacity-40"
            >
              <ArrowRight size={12} />
              Move right
            </button>
            <div className="my-1 h-px bg-surface-border/60" />
            <div className="px-2 pb-1 pt-1 text-[10px] uppercase tracking-[0.08em] text-text-dim/70">Session</div>
            <button
              type="button"
              disabled={!sessionId}
              onClick={() => {
                setTitle(header.title);
                setRenaming(true);
                setMenuOpen(false);
              }}
              className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay disabled:opacity-50"
            >
              Rename
            </button>
            {!header.primary && (
              <button
                type="button"
                onClick={() => {
                  onMakePrimary();
                  setMenuOpen(false);
                }}
                className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-text hover:bg-surface-overlay"
              >
                Set as channel primary
              </button>
            )}
            <div className="my-1 h-px bg-surface-border/60" />
            <button
              type="button"
              onClick={onClose}
              className="block w-full rounded px-2 py-1.5 text-left text-[12px] text-danger hover:bg-danger/10"
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function ChannelChatPaneGroup({
  channelId,
  botId,
  activeSessionId,
  panes,
  widths,
  focusedPaneId,
  maximizedPaneId,
  catalog,
  primaryNode,
  emptyState,
  chatMode = "default",
  onFocusPane,
  onClosePane,
  onMaximizePane,
  onRestorePanes,
  onMinimizePane,
  onMovePane,
  onCommitPaneWidths,
  onMakePrimary,
  onOpenSessions,
  onOpenSessionSplit,
  onToggleFocusLayout,
}: ChannelChatPaneGroupProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [localWidths, setLocalWidths] = useState<Record<string, number>>(widths);
  const localWidthsRef = useRef(localWidths);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    setLocalWidths(widths);
    localWidthsRef.current = widths;
  }, [widths, panes]);

  useEffect(() => () => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
  }, []);

  const visiblePanes = maximizedPaneId
    ? panes.filter((pane) => pane.id === maximizedPaneId)
    : panes;
  const total = visiblePanes.reduce((sum, pane) => sum + (localWidths[pane.id] ?? 0), 0) || visiblePanes.length || 1;
  if (visiblePanes.length === 1 && visiblePanes[0]?.surface.kind === "primary" && !maximizedPaneId) {
    return (
      <div
        ref={containerRef}
        className="flex min-h-0 flex-1"
        onMouseDown={() => onFocusPane(visiblePanes[0]!.id)}
      >
        {primaryNode}
      </div>
    );
  }

  if (visiblePanes.length === 0) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center bg-surface p-6">
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <div className="text-[15px] font-semibold text-text">No chat panes open</div>
          <div className="text-[12px] leading-relaxed text-text-dim">
            Add the primary session or split another session into this channel canvas.
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onOpenSessions} className="rounded-md border border-surface-border px-3 py-1.5 text-[12px] text-text hover:bg-surface-overlay">
              Open session
            </button>
            <button type="button" onClick={onOpenSessionSplit} className="rounded-md border border-surface-border px-3 py-1.5 text-[12px] text-text hover:bg-surface-overlay">
              Add split
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="flex min-h-0 flex-1 overflow-hidden bg-surface">
      {visiblePanes.map((pane, index) => {
        const width = ((localWidths[pane.id] ?? 1 / panes.length) / total) * 100;
        const focused = pane.id === focusedPaneId;
        const maximized = pane.id === maximizedPaneId;
        const body = pane.surface.kind === "primary"
          ? primaryNode
          : (
              <ChatSession
                source={pane.surface.kind === "scratch"
                  ? buildScratchChatSource({ channelId, botId, sessionId: pane.surface.sessionId })
                  : buildChannelSessionChatSource({ channelId, botId, sessionId: pane.surface.sessionId })}
                shape="fullpage"
                open
                onClose={() => onClosePane(pane.id)}
                title="Session"
                emptyState={emptyState}
                chatMode={chatMode}
                onOpenSessions={onOpenSessions}
                onOpenSessionSplit={onOpenSessionSplit}
                onToggleFocusLayout={onToggleFocusLayout}
              />
            );
        return (
          <div key={pane.id} className="flex min-w-[260px] min-h-0" style={{ flex: `${width} 1 0` }}>
            <div
              role="button"
              tabIndex={-1}
              onMouseDown={() => onFocusPane(pane.id)}
              className="flex min-w-0 flex-1 flex-col overflow-hidden bg-surface"
            >
              <PaneHeader
                pane={pane}
                channelId={channelId}
                activeSessionId={activeSessionId}
                catalog={catalog}
                focused={focused}
                maximized={maximized}
                onClose={() => onClosePane(pane.id)}
                onMaximize={() => onMaximizePane(pane.id)}
                onRestore={onRestorePanes}
                onMinimize={() => onMinimizePane(pane.id)}
                onMoveLeft={() => onMovePane(pane.id, "left")}
                onMoveRight={() => onMovePane(pane.id, "right")}
                onMakePrimary={() => onMakePrimary(pane)}
                canMoveLeft={index > 0}
                canMoveRight={index < visiblePanes.length - 1}
              />
              <div className="flex min-h-0 flex-1 flex-col">{body}</div>
            </div>
            {index < visiblePanes.length - 1 && (
              <div
                className="flex w-2 shrink-0 cursor-col-resize items-stretch justify-center bg-surface"
                onMouseDown={(event) => {
                  event.preventDefault();
                  const startX = event.clientX;
                  const rect = containerRef.current?.getBoundingClientRect();
                  const widthPx = rect?.width || 1;
                  const leftId = pane.id;
                  const rightId = visiblePanes[index + 1]!.id;
                  const startWidths = { ...localWidthsRef.current };
                  const applyDelta = (clientX: number) => {
                    const deltaRatio = (clientX - startX) / widthPx;
                    const next = resizeChannelChatPanes(
                      { panes, focusedPaneId, widths: startWidths, maximizedPaneId: maximizedPaneId ?? null, miniPane: null },
                      leftId,
                      rightId,
                      deltaRatio,
                    ).widths;
                    localWidthsRef.current = next;
                    setLocalWidths(next);
                  };
                  const onMove = (moveEvent: MouseEvent) => {
                    const clientX = moveEvent.clientX;
                    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
                    frameRef.current = requestAnimationFrame(() => {
                      frameRef.current = null;
                      applyDelta(clientX);
                    });
                  };
                  const onUp = (upEvent: MouseEvent) => {
                    if (frameRef.current !== null) {
                      cancelAnimationFrame(frameRef.current);
                      frameRef.current = null;
                    }
                    applyDelta(upEvent.clientX);
                    onCommitPaneWidths(localWidthsRef.current);
                    window.removeEventListener("mousemove", onMove);
                    window.removeEventListener("mouseup", onUp);
                  };
                  window.addEventListener("mousemove", onMove);
                  window.addEventListener("mouseup", onUp);
                }}
              >
                <div className="w-px bg-surface-border/70" />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
