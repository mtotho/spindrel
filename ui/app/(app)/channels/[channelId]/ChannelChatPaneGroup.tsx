import { useMemo, useRef, useState, type ReactNode } from "react";
import { MoreHorizontal, X as CloseIcon } from "lucide-react";
import { ChatSession } from "@/src/components/chat/ChatSession";
import { useRenameSession } from "@/src/api/hooks/useChannelSessions";
import {
  buildChannelSessionChatSource,
  buildScratchChatSource,
  formatScratchSessionTimestamp,
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
  catalog?: ChannelSessionCatalogItem[] | null;
  primaryNode: ReactNode;
  emptyState?: ReactNode;
  chatMode?: "default" | "terminal";
  onFocusPane: (paneId: string) => void;
  onClosePane: (paneId: string) => void;
  onResizePanePair: (leftPaneId: string, rightPaneId: string, deltaRatio: number) => void;
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

function PaneHeader({
  pane,
  channelId,
  activeSessionId,
  catalog,
  focused,
  onClose,
  onMakePrimary,
}: {
  pane: ChannelChatPane;
  channelId: string;
  activeSessionId?: string | null;
  catalog?: ChannelSessionCatalogItem[] | null;
  focused: boolean;
  onClose: () => void;
  onMakePrimary: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState("");
  const rename = useRenameSession();
  const sessionId = sessionIdForPane(pane, activeSessionId);
  const header = labelForPane(pane, catalog);
  const tooltip = [header.title, header.meta].filter(Boolean).join(" · ");

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
    <div className={`flex h-9 shrink-0 items-center gap-2 border-b px-3 ${focused ? "border-accent/35 bg-surface-overlay/25" : "border-surface-border/70 bg-surface"}`}>
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
            <span className="min-w-0 max-w-[62%] truncate text-[12px] font-semibold text-text">{header.title}</span>
            <span className="shrink-0 rounded-sm border border-surface-border/80 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-text-dim">
              {header.kind}
            </span>
            {!header.primary && pane.surface.kind === "channel" && (
              <span className="shrink-0 rounded-sm border border-surface-border/80 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-text-dim">
                Web-only
              </span>
            )}
          </div>
        )}
      </div>
      <div className="relative shrink-0">
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            setMenuOpen((open) => !open);
          }}
          className="flex h-7 w-7 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
          aria-label="Session pane actions"
        >
          <MoreHorizontal size={14} />
        </button>
        {menuOpen && (
          <div className="absolute right-0 top-8 z-20 w-36 rounded-md border border-surface-border bg-surface-raised p-1 shadow-lg">
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
                Make primary
              </button>
            )}
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
      <button
        type="button"
        onClick={onClose}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
        aria-label="Close pane"
      >
        <CloseIcon size={13} />
      </button>
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
  catalog,
  primaryNode,
  emptyState,
  chatMode = "default",
  onFocusPane,
  onClosePane,
  onResizePanePair,
  onMakePrimary,
  onOpenSessions,
  onOpenSessionSplit,
  onToggleFocusLayout,
}: ChannelChatPaneGroupProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const total = panes.reduce((sum, pane) => sum + (widths[pane.id] ?? 0), 0) || panes.length || 1;
  if (panes.length === 1 && panes[0]?.surface.kind === "primary") {
    return (
      <div
        ref={containerRef}
        className="flex min-h-0 flex-1"
        onMouseDown={() => onFocusPane(panes[0]!.id)}
      >
        {primaryNode}
      </div>
    );
  }

  if (panes.length === 0) {
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
      {panes.map((pane, index) => {
        const width = ((widths[pane.id] ?? 1 / panes.length) / total) * 100;
        const focused = pane.id === focusedPaneId;
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
              className={`flex min-w-0 flex-1 flex-col overflow-hidden bg-surface ${index === 0 ? "" : "border-l border-surface-border/70"}`}
            >
              <PaneHeader
                pane={pane}
                channelId={channelId}
                activeSessionId={activeSessionId}
                catalog={catalog}
                focused={focused}
                onClose={() => onClosePane(pane.id)}
                onMakePrimary={() => onMakePrimary(pane)}
              />
              <div className="flex min-h-0 flex-1 flex-col">{body}</div>
            </div>
            {index < panes.length - 1 && (
              <div
                className="flex w-2 shrink-0 cursor-col-resize items-stretch justify-center bg-surface"
                onMouseDown={(event) => {
                  event.preventDefault();
                  const startX = event.clientX;
                  const rect = containerRef.current?.getBoundingClientRect();
                  const widthPx = rect?.width || 1;
                  const leftId = pane.id;
                  const rightId = panes[index + 1]!.id;
                  const onMove = (moveEvent: MouseEvent) => {
                    onResizePanePair(leftId, rightId, (moveEvent.clientX - startX) / widthPx);
                  };
                  const onUp = () => {
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
