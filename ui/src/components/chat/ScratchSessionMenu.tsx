import { useEffect, useMemo, useRef, useState } from "react";
import {
  usePromoteScratchSession,
  useRenameSession,
  useResetScratchSession,
  useScratchHistory,
  useScratchSession,
} from "@/src/api/hooks/useEphemeralSession";
import { Check, Loader2, RotateCcw, StickyNote, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  formatScratchSessionTimestamp,
  getScratchSessionLabel,
  getScratchSessionStats,
  isUntouchedDraftSession,
} from "@/src/lib/channelSessionSurfaces";

interface ScratchSessionMenuProps {
  open: boolean;
  onClose: () => void;
  channelId: string;
  botId: string | null | undefined;
  currentSessionId?: string | null;
  mobile?: boolean;
  onOpenSidePane?: (sessionId: string) => void;
  onOpenMainChat?: () => void;
  onStartNewSession?: () => void;
  onNavigateSession: (sessionId: string) => void;
}

function handleButtonLikeKeyDown(
  event: React.KeyboardEvent<HTMLElement>,
  onActivate: () => void,
) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onActivate();
  }
}

export function ScratchSessionMenu({
  open,
  onClose,
  channelId,
  botId,
  currentSessionId,
  mobile = false,
  onOpenSidePane,
  onOpenMainChat,
  onStartNewSession,
  onNavigateSession,
}: ScratchSessionMenuProps) {
  const t = useThemeTokens();
  const desktopPanelStyle = !mobile
    ? {
        border: "none",
        borderRadius: 0,
      }
    : undefined;
  const panelRef = useRef<HTMLDivElement | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const canQueryCurrent = !!channelId && !!botId;
  const { data: currentSession, isLoading: isCurrentSessionLoading } = useScratchSession(
    open && canQueryCurrent ? channelId : null,
    open && canQueryCurrent ? botId! : null,
  );
  const { data: history, isLoading, error } = useScratchHistory(open ? channelId : null);
  const resetScratch = useResetScratchSession();
  const renameSession = useRenameSession();
  const promoteScratch = usePromoteScratchSession();

  useEffect(() => {
    if (!open || mobile) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (panelRef.current && target && !panelRef.current.contains(target)) onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [mobile, onClose, open]);

  const visibleHistory = useMemo(() => {
    if (!history) return [];
    return history.filter((row) => row.session_id !== currentSessionId).slice(0, 4);
  }, [history]);
  const showPrimarySessionRow = !!currentSessionId && !!onOpenMainChat;
  const currentRow = useMemo(() => {
    if (!currentSessionId) return null;
    const fromHistory = history?.find((row) => row.session_id === currentSessionId);
    if (fromHistory) return fromHistory;
    if (!currentSession || currentSession.session_id !== currentSessionId) return null;
    return {
      session_id: currentSession.session_id,
      bot_id: currentSession.bot_id,
      created_at: currentSession.created_at,
      last_active: currentSession.created_at,
      is_current: currentSession.is_current,
      message_count: currentSession.message_count ?? 0,
      preview: currentSession.title?.trim() || undefined,
      title: currentSession.title,
      summary: currentSession.summary,
      section_count: currentSession.section_count ?? 0,
      session_scope: currentSession.session_scope,
    };
  }, [currentSession, currentSessionId, history]);

  const reusableDraftSessionId = useMemo(() => {
    if (!isUntouchedDraftSession(currentSession)) return null;
    return currentSession?.session_id ?? null;
  }, [currentSession]);
  const waitingOnCurrentSession = canQueryCurrent && isCurrentSessionLoading && !currentSession;
  const activateSessionRow = (sessionId: string) => {
    onClose();
    if (!mobile && !currentSessionId && onOpenSidePane) {
      onOpenSidePane(sessionId);
    } else {
      onNavigateSession(sessionId);
    }
  };
  const saveRename = (sessionId: string) => {
    renameSession.mutate(
      {
        session_id: sessionId,
        title: editingTitle.trim(),
        parent_channel_id: channelId,
        bot_id: botId ?? undefined,
      },
      {
        onSuccess: () => {
          setEditingSessionId(null);
          setEditingTitle("");
        },
      },
    );
  };

  if (!open) return null;

  const isEditingCurrentSession = editingSessionId === currentRow?.session_id;

  const panel = (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal={mobile ? "true" : undefined}
      aria-label="Sessions"
      className={
        mobile
          ? "fixed inset-0 z-[9996] flex flex-col overflow-hidden bg-surface-raised"
          : "absolute right-0 top-full z-[80] mt-0.5 flex w-[328px] max-w-[calc(100vw-16px)] flex-col overflow-hidden bg-surface-raised shadow-[0_8px_32px_rgba(0,0,0,0.4)]"
      }
      style={desktopPanelStyle}
    >
      <div className={`flex items-center gap-2 border-b border-surface-border px-3 py-2.5 ${mobile ? "pt-4" : ""}`}>
        <StickyNote size={14} className="shrink-0 text-text-dim" />
        <div className="min-w-0 flex-1 text-[12px] font-medium text-text">Session</div>
        <button
          type="button"
          onClick={() => {
            if (reusableDraftSessionId) {
              onClose();
              if (!mobile && !currentSessionId && onOpenSidePane) {
                onOpenSidePane(reusableDraftSessionId);
              } else {
                onNavigateSession(reusableDraftSessionId);
              }
              return;
            }
            if (!botId) return;
            resetScratch.mutate(
              { parent_channel_id: channelId, bot_id: botId },
              {
                onSuccess: (data) => {
                  onStartNewSession?.();
                  onClose();
                  if (!mobile && !currentSessionId && onOpenSidePane) {
                    onOpenSidePane(data.session_id);
                  } else {
                    onNavigateSession(data.session_id);
                  }
                },
              },
            );
          }}
          disabled={!botId || resetScratch.isPending || waitingOnCurrentSession}
          className="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[11px] font-medium text-text-dim transition-colors hover:bg-surface-overlay hover:text-text disabled:cursor-not-allowed disabled:opacity-50"
          title="Start a new session in this channel"
        >
          {resetScratch.isPending || waitingOnCurrentSession ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <RotateCcw size={12} />
          )}
          New session
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
          aria-label="Close sessions menu"
        >
          <X size={14} />
        </button>
      </div>

      <div className="overflow-y-auto py-1.5">
        {!currentSession && canQueryCurrent ? (
          <div className="px-3 py-2 text-[12px] text-text-dim">
            Loading session…
          </div>
        ) : null}
        {!canQueryCurrent ? (
          <div className="px-3 py-2 text-[12px] text-text-dim">
            Pick a bot to start a new session in this channel.
          </div>
        ) : null}

        {currentRow ? (
          <>
              <div className="px-3 pb-1 pt-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-text-dim">
              This session
            </div>
            <div
              role={isEditingCurrentSession ? undefined : "button"}
              tabIndex={isEditingCurrentSession ? -1 : 0}
              onClick={isEditingCurrentSession ? undefined : () => activateSessionRow(currentRow.session_id)}
              onKeyDown={isEditingCurrentSession ? undefined : (event) => handleButtonLikeKeyDown(event, () => activateSessionRow(currentRow.session_id))}
              className={`flex items-start gap-3 bg-surface-overlay px-3 py-2 transition-colors ${isEditingCurrentSession ? "" : "cursor-pointer hover:bg-surface-overlay"}`}
            >
              <div className="min-w-0 flex-1">
                {isEditingCurrentSession ? (
                  <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
                    <input
                      autoFocus
                      value={editingTitle}
                      onChange={(event) => setEditingTitle(event.target.value)}
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => {
                        event.stopPropagation();
                        if (event.key === "Enter") {
                          event.preventDefault();
                          saveRename(currentRow.session_id);
                        } else if (event.key === "Escape") {
                          event.preventDefault();
                          setEditingSessionId(null);
                          setEditingTitle("");
                        }
                      }}
                      className="min-w-0 flex-1 rounded-md border border-surface-border bg-surface px-2 py-1 text-[12px] text-text outline-none transition-colors focus:border-accent"
                      aria-label="Session name"
                    />
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        saveRename(currentRow.session_id);
                      }}
                      disabled={renameSession.isPending}
                      className="rounded-md p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text disabled:opacity-50"
                      aria-label="Save session name"
                      title="Save"
                    >
                      <Check size={12} />
                    </button>
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        setEditingSessionId(null);
                        setEditingTitle("");
                      }}
                      className="rounded-md p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
                      aria-label="Cancel rename"
                      title="Cancel"
                    >
                      <X size={12} />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-start justify-between gap-2">
                    <div className="truncate text-[12px] font-medium text-text">{getScratchSessionLabel(currentRow)}</div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditingSessionId(currentRow.session_id);
                          setEditingTitle(currentRow.title?.trim() || "");
                        }}
                        className="inline-flex h-6 items-center px-0 text-[11px] font-medium text-text-dim transition-colors hover:text-text disabled:opacity-50"
                        aria-label="Rename session"
                        title="Rename"
                        disabled={renameSession.isPending}
                      >
                        Rename
                      </button>
                      <span
                        className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                        style={{ background: t.surface, color: t.textDim }}
                      >
                        Current
                      </span>
                    </div>
                  </div>
                )}
                <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-text-dim">
                  <span>{formatScratchSessionTimestamp(currentRow.last_active)}</span>
                  {showPrimarySessionRow ? (
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        promoteScratch.mutate(
                          {
                            session_id: currentRow.session_id,
                            parent_channel_id: channelId,
                            bot_id: botId ?? undefined,
                          },
                          {
                            onSuccess: () => {
                              onClose();
                              onOpenMainChat?.();
                            },
                          },
                        );
                      }}
                      disabled={promoteScratch.isPending}
                      className="inline-flex h-6 items-center px-0 text-[11px] font-medium text-text-dim transition-colors hover:text-text disabled:opacity-50"
                      aria-label="Make primary session"
                      title="Make primary"
                    >
                      Make primary
                    </button>
                  ) : null}
                </div>
                <div className="mt-1 text-[11px] text-text-dim">
                  {getScratchSessionStats(currentRow)}
                </div>
              </div>
            </div>
          </>
        ) : null}

        {showPrimarySessionRow ? (
          <div
            role="button"
            tabIndex={0}
            onClick={() => {
              onClose();
              onOpenMainChat?.();
            }}
            onKeyDown={(event) => handleButtonLikeKeyDown(event, () => {
              onClose();
              onOpenMainChat?.();
            })}
            className="flex cursor-pointer items-start gap-3 px-3 py-2 transition-colors hover:bg-surface-overlay"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-[12px] font-medium text-text">Primary session</div>
              <div className="mt-1 text-[11px] text-text-dim">
                Return to the channel&apos;s default conversation
              </div>
            </div>
          </div>
        ) : null}

        <div className="px-3 pb-1 pt-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-text-dim">
          Recent sessions
        </div>
        {isLoading && <div className="px-3 py-2 text-[12px] text-text-dim">Loading sessions…</div>}
        {error && (
          <div className="px-3 py-2 text-[12px]" style={{ color: t.dangerMuted }}>
            {error instanceof Error ? error.message : "Failed to load sessions."}
          </div>
        )}
        {!isLoading && !error && visibleHistory.length === 0 && (
          <div className="px-3 py-2 text-[12px] text-text-dim">No prior sessions yet.</div>
        )}
        {!isLoading && !error && visibleHistory.length > 0 && (
          <ul>
            {visibleHistory.map((row) => {
              const isEditingSession = editingSessionId === row.session_id;
              const showPromoteAction = !!onOpenMainChat;
              return (
                <li key={row.session_id}>
                  <div
                    role={isEditingSession ? undefined : "button"}
                    tabIndex={isEditingSession ? -1 : 0}
                    onClick={isEditingSession ? undefined : () => activateSessionRow(row.session_id)}
                    onKeyDown={isEditingSession ? undefined : (event) => handleButtonLikeKeyDown(event, () => activateSessionRow(row.session_id))}
                    className={`group flex items-start gap-3 px-3 py-2 transition-colors ${isEditingSession ? "" : "cursor-pointer hover:bg-surface-overlay"}`}
                  >
                    <div className="min-w-0 flex-1">
                      {isEditingSession ? (
                        <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
                          <input
                            autoFocus
                            value={editingTitle}
                            onChange={(event) => setEditingTitle(event.target.value)}
                            onClick={(event) => event.stopPropagation()}
                            onKeyDown={(event) => {
                              event.stopPropagation();
                              if (event.key === "Enter") {
                                event.preventDefault();
                                saveRename(row.session_id);
                              } else if (event.key === "Escape") {
                                event.preventDefault();
                                setEditingSessionId(null);
                                setEditingTitle("");
                              }
                            }}
                            className="min-w-0 flex-1 rounded-md border border-surface-border bg-surface px-2 py-1 text-[12px] text-text outline-none transition-colors focus:border-accent"
                            aria-label="Session name"
                          />
                          <button
                            type="button"
                            onClick={() => saveRename(row.session_id)}
                            disabled={renameSession.isPending}
                            className="rounded-md p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text disabled:opacity-50"
                            aria-label="Save session name"
                            title="Save"
                          >
                            <Check size={12} />
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setEditingSessionId(null);
                              setEditingTitle("");
                            }}
                            className="rounded-md p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
                            aria-label="Cancel rename"
                            title="Cancel"
                          >
                            <X size={12} />
                          </button>
                        </div>
                      ) : (
                        <div className="block w-full text-left">
                          <div className="flex items-start justify-between gap-2">
                            <div className="truncate text-[12px] font-medium text-text">{getScratchSessionLabel(row)}</div>
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                setEditingSessionId(row.session_id);
                                setEditingTitle(row.title?.trim() || "");
                              }}
                              className="inline-flex h-6 items-center px-0 text-[11px] font-medium text-text-dim transition-colors hover:text-text disabled:opacity-50"
                              aria-label="Rename session"
                              title="Rename"
                              disabled={renameSession.isPending}
                            >
                              Rename
                            </button>
                          </div>
                        </div>
                      )}
                      <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-text-dim">
                        <span>{formatScratchSessionTimestamp(row.last_active)}</span>
                        {showPromoteAction ? (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              promoteScratch.mutate(
                                {
                                  session_id: row.session_id,
                                  parent_channel_id: channelId,
                                  bot_id: botId ?? undefined,
                                },
                                {
                                  onSuccess: () => {
                                    onClose();
                                    onOpenMainChat?.();
                                  },
                                },
                              );
                            }}
                            disabled={promoteScratch.isPending}
                            className="inline-flex h-6 items-center px-0 text-[11px] font-medium text-text-dim transition-colors hover:text-text disabled:opacity-50"
                            aria-label="Make primary session"
                            title="Make primary"
                          >
                            Make primary
                          </button>
                        ) : null}
                      </div>
                      <div className="mt-1 text-[11px] text-text-dim">
                        {getScratchSessionStats(row)}
                      </div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );

  if (!mobile) return panel;

  return (
    <>
      <div className="fixed inset-0 z-[9995] bg-black/40" onClick={onClose} aria-hidden="true" />
      {panel}
    </>
  );
}
