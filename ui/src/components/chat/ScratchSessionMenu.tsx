import { useEffect, useMemo, useRef, useState } from "react";
import {
  usePromoteScratchSession,
  useRenameSession,
  useResetScratchSession,
  useScratchHistory,
  useScratchSession,
} from "@/src/api/hooks/useEphemeralSession";
import { ArrowUpCircle, Check, Loader2, Pencil, RotateCcw, StickyNote, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

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

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "?";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function previewLabel(preview?: string): string {
  const raw = preview?.trim();
  if (!raw) return "Untitled session";
  return raw;
}

function sessionLabel(row: { title?: string | null; preview?: string }): string {
  const title = row.title?.trim();
  if (title) return title;
  return previewLabel(row.preview);
}

function isUntouchedDraftSession(session: {
  message_count?: number;
  section_count?: number;
  title?: string | null;
  summary?: string | null;
  preview?: string;
} | null | undefined): boolean {
  if (!session) return false;
  const messageCount = session.message_count ?? 0;
  const sectionCount = session.section_count ?? 0;
  if (messageCount !== 0 || sectionCount !== 0) return false;
  if ((session.title || "").trim()) return false;
  if ((session.summary || "").trim()) return false;
  if ((session.preview || "").trim()) return false;
  return true;
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
    return history.slice(0, 4);
  }, [history]);

  const reusableDraftSessionId = useMemo(() => {
    if (!isUntouchedDraftSession(currentSession)) return null;
    return currentSession?.session_id ?? null;
  }, [currentSession]);
  const waitingOnCurrentSession = canQueryCurrent && isCurrentSessionLoading && !currentSession;
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

  const panel = (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal={mobile ? "true" : undefined}
      aria-label="Sessions"
      className={
        mobile
          ? "fixed inset-x-3 bottom-3 top-20 z-[9996] flex flex-col overflow-hidden rounded-md border border-surface-border bg-surface-raised shadow-2xl"
          : "absolute right-0 top-full z-[80] mt-1.5 flex w-[360px] max-w-[calc(100vw-24px)] flex-col overflow-hidden rounded-md border border-surface-border bg-surface-raised shadow-xl"
      }
    >
      <div className="flex items-center gap-2 border-b border-surface-border px-3 py-2">
        <StickyNote size={14} className="shrink-0 text-text-dim" />
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-text">Session</div>
          <div className="truncate text-[11px] text-text-dim">
            Start a new session in this channel or reopen a recent one without replacing the main channel chat
          </div>
        </div>
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

      <div className="overflow-y-auto py-1">
        {currentSessionId && onOpenMainChat ? (
          <>
            <button
              type="button"
              onClick={() => {
                onClose();
                onOpenMainChat();
              }}
              className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-[12px] text-text transition-colors hover:bg-surface-overlay"
            >
              Open main channel chat
            </button>
            <div className="mx-3 my-1 h-px bg-surface-border" />
          </>
        ) : null}
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

        <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-text-dim">
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
              const isViewingSession = row.session_id === currentSessionId;
              const isEditingSession = editingSessionId === row.session_id;
              return (
                <li key={row.session_id}>
                  <div className="flex items-start gap-3 px-3 py-2 transition-colors hover:bg-surface-overlay">
                    <div className="min-w-0 flex-1">
                      {isEditingSession ? (
                        <div className="flex items-center gap-1">
                          <input
                            autoFocus
                            value={editingTitle}
                            onChange={(event) => setEditingTitle(event.target.value)}
                            onKeyDown={(event) => {
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
                        <button
                          type="button"
                          onClick={() => {
                            onClose();
                            if (!mobile && !currentSessionId && onOpenSidePane) {
                              onOpenSidePane(row.session_id);
                            } else {
                              onNavigateSession(row.session_id);
                            }
                          }}
                          className="block w-full cursor-pointer text-left"
                        >
                          <div className="truncate text-[12px] text-text">{sessionLabel(row)}</div>
                        </button>
                      )}
                      {row.summary?.trim() ? (
                        <div className="mt-0.5 line-clamp-2 text-[11px] text-text-dim">{row.summary.trim()}</div>
                      ) : null}
                      <div className="mt-0.5 text-[11px] text-text-dim">
                        {formatTimestamp(row.last_active)} · {row.message_count} msg{row.message_count === 1 ? "" : "s"} · {row.section_count ?? 0} section{(row.section_count ?? 0) === 1 ? "" : "s"}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditingSessionId(row.session_id);
                          setEditingTitle(row.title?.trim() || "");
                        }}
                        className="rounded-md p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
                        aria-label="Rename session"
                        title="Rename"
                        disabled={renameSession.isPending}
                      >
                        <Pencil size={12} />
                      </button>
                      {!row.is_current && (
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
                          className="rounded-md p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
                          aria-label="Make primary session"
                          title="Make primary"
                        >
                          <ArrowUpCircle size={12} />
                        </button>
                      )}
                      {isViewingSession && (
                        <span
                          className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]"
                          style={{ background: t.accentSubtle, color: t.accent }}
                        >
                          Viewing
                        </span>
                      )}
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
