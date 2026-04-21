import { useEffect, useMemo, useRef } from "react";
import { useResetScratchSession, useScratchHistory, useScratchSession } from "@/src/api/hooks/useEphemeralSession";
import { Loader2, RotateCcw, StickyNote, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

interface ScratchSessionMenuProps {
  open: boolean;
  onClose: () => void;
  channelId: string;
  botId: string | null | undefined;
  currentSessionId?: string | null;
  mobile?: boolean;
  onOpenSidePane?: () => void;
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
  if (!raw) return "Untitled scratch";
  return raw;
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
  const canQueryCurrent = !!channelId && !!botId;
  const { data: currentSession } = useScratchSession(
    open && canQueryCurrent ? channelId : null,
    open && canQueryCurrent ? botId! : null,
  );
  const { data: history, isLoading, error } = useScratchHistory(open ? channelId : null);
  const resetScratch = useResetScratchSession();

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

  if (!open) return null;

  const panel = (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal={mobile ? "true" : undefined}
      aria-label="Scratch sessions"
      className={
        mobile
          ? "fixed inset-x-3 bottom-3 top-20 z-[9996] flex flex-col overflow-hidden rounded-md border border-surface-border bg-surface-raised shadow-2xl"
          : "absolute right-0 top-full z-[80] mt-1.5 flex w-[360px] max-w-[calc(100vw-24px)] flex-col overflow-hidden rounded-md border border-surface-border bg-surface-raised shadow-xl"
      }
    >
      <div className="flex items-center gap-2 border-b border-surface-border px-3 py-2">
        <StickyNote size={14} className="shrink-0 text-text-dim" />
        <div className="min-w-0 flex-1">
          <div className="text-[12px] font-medium text-text">Scratch session</div>
          <div className="truncate text-[11px] text-text-dim">Separate session attached to this channel</div>
        </div>
        <button
          type="button"
          onClick={() => {
            if (!botId) return;
            resetScratch.mutate(
              { parent_channel_id: channelId, bot_id: botId },
              {
                onSuccess: (data) => {
                  onStartNewSession?.();
                  onClose();
                  onNavigateSession(data.session_id);
                },
              },
            );
          }}
          disabled={!botId || resetScratch.isPending}
          className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-[11px] font-medium text-text hover:bg-surface-overlay disabled:cursor-not-allowed disabled:opacity-50"
        >
          {resetScratch.isPending ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
          New
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
          aria-label="Close scratch session menu"
        >
          <X size={14} />
        </button>
      </div>

      <div className="overflow-y-auto py-1">
        {currentSession ? (
          <>
            {onOpenSidePane && !currentSessionId && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onOpenSidePane();
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-text transition-colors hover:bg-surface-overlay"
              >
                Open mini chat
              </button>
            )}
            {currentSessionId && onOpenMainChat && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onOpenMainChat();
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-text transition-colors hover:bg-surface-overlay"
              >
                Return to channel
              </button>
            )}
            {(onOpenSidePane && !currentSessionId) || (currentSessionId && onOpenMainChat) ? (
              <div className="mx-3 my-1 h-px bg-surface-border" />
            ) : null}
          </>
        ) : (
          <div className="px-3 py-2 text-[12px] text-text-dim">
            {canQueryCurrent ? "Loading scratch session…" : "Pick a bot to start a scratch session."}
          </div>
        )}

        <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-text-dim">
          Recent
        </div>
        {isLoading && <div className="px-3 py-2 text-[12px] text-text-dim">Loading scratch sessions…</div>}
        {error && (
          <div className="px-3 py-2 text-[12px]" style={{ color: t.dangerMuted }}>
            {error instanceof Error ? error.message : "Failed to load scratch sessions."}
          </div>
        )}
        {!isLoading && !error && visibleHistory.length === 0 && (
          <div className="px-3 py-2 text-[12px] text-text-dim">No prior scratch sessions yet.</div>
        )}
        {!isLoading && !error && visibleHistory.length > 0 && (
          <ul>
            {visibleHistory.map((row) => {
              const isActiveView = row.session_id === currentSessionId;
              return (
                <li key={row.session_id}>
                  <button
                    type="button"
                    onClick={() => {
                      onClose();
                      onNavigateSession(row.session_id);
                    }}
                    className="flex w-full items-start gap-3 px-3 py-2 text-left transition-colors hover:bg-surface-overlay"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[12px] text-text">{previewLabel(row.preview)}</div>
                      <div className="mt-0.5 text-[11px] text-text-dim">
                        {formatTimestamp(row.last_active)} · {row.message_count} msg{row.message_count === 1 ? "" : "s"}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      {isActiveView && (
                        <span
                          className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]"
                          style={{ background: t.accentSubtle, color: t.accent }}
                        >
                          Open
                        </span>
                      )}
                    </div>
                  </button>
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
