import { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Check, Columns2, CornerDownLeft, MessageSquare, Plus, Search, Star, X } from "lucide-react";
import {
  buildChannelSessionPickerGroups,
  buildChannelSessionPickerEntries,
  isUntouchedDraftSession,
  type ChannelSessionActivationIntent,
  type ChannelSessionPickerEntry,
  type ChannelSessionSurface,
} from "@/src/lib/channelSessionSurfaces";
import {
  useChannelSessionCatalog,
  useChannelSessionSearch,
  usePromoteScratchSession,
  useRenameSession,
  useResetScratchSession,
  useScratchHistory,
} from "@/src/api/hooks/useChannelSessions";

interface SessionPickerOverlayProps {
  open: boolean;
  onClose: () => void;
  channelId: string;
  botId?: string | null;
  channelLabel?: string | null;
  selectedSessionId?: string | null;
  onActivateSurface: (surface: ChannelSessionSurface, intent: ChannelSessionActivationIntent) => void;
  allowSplit?: boolean;
  mode?: "switch" | "split";
  hiddenSurfaces?: ChannelSessionSurface[];
}

export function SessionPickerOverlay({
  open,
  onClose,
  channelId,
  botId,
  channelLabel,
  selectedSessionId,
  onActivateSurface,
  allowSplit = false,
  mode = "switch",
  hiddenSurfaces = [],
}: SessionPickerOverlayProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { data: history, isLoading, error } = useScratchHistory(open ? channelId : null);
  const { data: channelSessions, isLoading: catalogLoading, error: catalogError } = useChannelSessionCatalog(open ? channelId : null);
  const resetScratch = useResetScratchSession();
  const promoteScratch = usePromoteScratchSession();
  const renameSession = useRenameSession();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [pickerMode, setPickerMode] = useState<"switch" | "split">(mode);

  useEffect(() => {
    if (!open) {
      setDebouncedQuery("");
      return;
    }
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [open, query]);

  const {
    data: deepMatches,
    isFetching: deepSearchLoading,
    error: deepSearchError,
  } = useChannelSessionSearch(open ? channelId : null, debouncedQuery);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    setEditingId(null);
    setPickerMode(mode);
    let innerFrame = 0;
    const a = requestAnimationFrame(() => {
      innerFrame = requestAnimationFrame(() => inputRef.current?.focus());
    });
    return () => {
      cancelAnimationFrame(a);
      if (innerFrame) cancelAnimationFrame(innerFrame);
    };
  }, [mode, open]);

  const hiddenKeys = useMemo(() => new Set(hiddenSurfaces.map((surface) => {
    if (surface.kind === "primary") return "primary";
    return `${surface.kind}:${surface.sessionId}`;
  })), [hiddenSurfaces]);

  const entries = useMemo(() => {
    const built = buildChannelSessionPickerEntries({
      channelLabel,
      selectedSessionId,
      history,
      channelSessions,
      deepMatches,
      query,
    });
    if (pickerMode !== "split") return built;
    return built.filter((entry) => {
      if (entry.surface.kind === "primary") return !hiddenKeys.has("primary");
      return !hiddenKeys.has(`${entry.surface.kind}:${entry.surface.sessionId}`);
    });
  }, [channelLabel, channelSessions, deepMatches, hiddenKeys, history, pickerMode, query, selectedSessionId]);

  const groups = useMemo(
    () => buildChannelSessionPickerGroups(entries, query),
    [entries, query],
  );

  useEffect(() => {
    setActiveIndex((idx) => Math.max(0, Math.min(idx, Math.max(entries.length - 1, 0))));
  }, [entries.length]);

  if (!open || typeof document === "undefined") return null;

  const choose = (entry: ChannelSessionPickerEntry) => {
    onClose();
    onActivateSurface(entry.surface, pickerMode === "split" ? "split" : "switch");
  };

  const startNewSession = () => {
    if (!botId) return;
    const intent = pickerMode === "split" ? "split" : "switch";
    const blankCurrent = (history ?? []).find((row) => row.is_current && isUntouchedDraftSession(row));
    if (blankCurrent) {
      onClose();
      onActivateSurface({ kind: "scratch", sessionId: blankCurrent.session_id }, intent);
      return;
    }
    resetScratch.mutate(
      { parent_channel_id: channelId, bot_id: botId },
      {
        onSuccess: (row) => {
          onClose();
          onActivateSurface({ kind: "scratch", sessionId: row.session_id }, intent);
        },
      },
    );
  };

  const saveRename = (entry: Extract<ChannelSessionPickerEntry, { kind: "scratch" }>) => {
    const title = editingTitle.trim();
    if (!title) return;
    renameSession.mutate(
      { session_id: entry.id, title, parent_channel_id: channelId, bot_id: entry.row.bot_id },
      {
        onSuccess: () => {
          setEditingId(null);
          setEditingTitle("");
        },
      },
    );
  };

  return ReactDOM.createPortal(
    <>
      <div
        className="fixed inset-0 z-[10040] bg-black/50 backdrop-blur-[3px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Switch sessions"
        className="fixed left-1/2 top-[12vh] z-[10041] flex max-h-[76vh] w-[640px] max-w-[94vw] -translate-x-1/2 flex-col overflow-hidden rounded-md border border-surface-border bg-surface-raised shadow-[0_16px_48px_rgba(0,0,0,0.38)]"
      >
        <div className="flex items-center gap-3 border-b border-surface-border px-4 py-3">
          <Search size={16} className="text-text-dim" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                if (query) setQuery("");
                else onClose();
              } else if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveIndex((idx) => Math.min(idx + 1, Math.max(entries.length - 1, 0)));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((idx) => Math.max(idx - 1, 0));
            } else if (event.key === "Enter") {
              event.preventDefault();
              const entry = entries[activeIndex];
              if (entry) {
                onClose();
                onActivateSurface(entry.surface, event.metaKey || event.ctrlKey ? "split" : pickerMode === "split" ? "split" : "switch");
              }
            }
          }}
            placeholder={pickerMode === "split" ? "Search session to split..." : "Search or pick a session..."}
            className="min-w-0 flex-1 bg-transparent text-[15px] text-text outline-none placeholder:text-text-dim"
          />
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex items-center justify-between gap-2 border-b border-surface-border px-4 py-2">
          <div className="min-w-0 text-[12px] text-text-dim">
            {pickerMode === "split"
              ? `Add split${channelLabel ? ` in #${channelLabel}` : ""}`
              : query.trim()
                ? `Search results${channelLabel ? ` in #${channelLabel}` : ""}`
                : `Showing recent sessions${channelLabel ? ` in #${channelLabel}` : ""}`}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {allowSplit && (
              <button
                type="button"
                onClick={() => setPickerMode((current) => current === "split" ? "switch" : "split")}
                className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text"
              >
                <Columns2 size={13} />
                {pickerMode === "split" ? "Switch mode" : "Add split"}
              </button>
            )}
            <button
              type="button"
              onClick={startNewSession}
              disabled={!botId || resetScratch.isPending}
              className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-accent transition-colors hover:bg-surface-overlay disabled:opacity-50"
            >
              <Plus size={13} />
              New session
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto py-1">
          {(isLoading || catalogLoading) && <div className="px-4 py-8 text-sm text-text-dim">Loading sessions...</div>}
          {(error || catalogError) && (
            <div className="px-4 py-8 text-sm text-danger">
              {error instanceof Error
                ? error.message
                : catalogError instanceof Error
                  ? catalogError.message
                  : "Failed to load sessions."}
            </div>
          )}
          {!isLoading && !catalogLoading && !deepSearchLoading && !error && !catalogError && entries.length === 0 && (
            <div className="px-4 py-8 text-sm text-text-dim">No sessions matched that search.</div>
          )}
          {!isLoading && !catalogLoading && !error && !catalogError && groups.map((group) => (
            <div key={group.id}>
              {groups.length > 1 && (
                <div className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wide text-text-muted">
                  {group.label}
                </div>
              )}
              {group.entries.map((entry) => {
                const index = entries.findIndex((candidate) => candidate.id === entry.id);
                const active = index === activeIndex;
            const scratch = entry.kind === "scratch" ? entry : null;
            const splitEligible = allowSplit
              && pickerMode === "switch"
              && (entry.kind === "scratch" || entry.kind === "channel");
            const editing = scratch && editingId === scratch.id;
            return (
              <div
                key={entry.id}
                role="button"
                tabIndex={-1}
                onMouseMove={() => setActiveIndex(index)}
                onClick={() => !editing && choose(entry)}
                className={`mx-1 flex cursor-pointer items-start gap-3 rounded-md px-3 py-2 transition-colors ${active ? "bg-accent/[0.08]" : ""}`}
              >
                <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-overlay text-text-dim">
                  {entry.kind === "primary" ? <MessageSquare size={14} /> : <Star size={13} />}
                </div>
                <div className="min-w-0 flex-1">
                  {editing && scratch ? (
                    <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
                      <input
                        autoFocus
                        value={editingTitle}
                        onChange={(event) => setEditingTitle(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            saveRename(scratch);
                          } else if (event.key === "Escape") {
                            event.preventDefault();
                            setEditingId(null);
                            setEditingTitle("");
                          }
                        }}
                        className="min-w-0 flex-1 rounded-md border border-surface-border bg-surface px-2 py-1 text-[13px] text-text outline-none focus:border-accent"
                      />
                      <button
                        type="button"
                        onClick={() => saveRename(scratch)}
                        className="rounded-md p-1 text-text-dim hover:bg-surface-overlay hover:text-text"
                        aria-label="Save session name"
                      >
                        <Check size={13} />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium text-text">{entry.label}</div>
                        <div className="mt-0.5 truncate text-[11px] text-text-dim">{entry.meta}</div>
                        {entry.matches && entry.matches.length > 0 && (
                          <div className="mt-1 space-y-1">
                            {entry.matches.slice(0, 2).map((match, matchIndex) => (
                              <div
                                key={`${match.kind}:${match.message_id ?? match.section_id ?? matchIndex}`}
                                className="truncate text-[11px] text-text-muted"
                              >
                                {match.kind === "section" ? "Section" : "Message"}: {match.preview}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        {entry.selected && (
                          <span className="rounded-full bg-accent/15 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                            Current
                          </span>
                        )}
                        {splitEligible && active && (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              onClose();
                              onActivateSurface(entry.surface, "split");
                            }}
                            className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium text-text-dim transition-colors hover:bg-surface-overlay hover:text-text"
                            title="Open this session as a split pane (Ctrl/Cmd+Enter)"
                          >
                            <Columns2 size={12} />
                            Split
                          </button>
                        )}
                        {active && <CornerDownLeft size={12} className="text-text-dim" />}
                      </div>
                    </div>
                  )}
                  {scratch && !editing && (
                    <div className="mt-1 flex items-center gap-3 text-[11px]">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditingId(scratch.id);
                          setEditingTitle(scratch.label === "Untitled session" ? "" : scratch.label);
                        }}
                        className="text-text-dim hover:text-text"
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        disabled={promoteScratch.isPending}
                        onClick={(event) => {
                          event.stopPropagation();
                          promoteScratch.mutate({
                            session_id: scratch.id,
                            parent_channel_id: channelId,
                            bot_id: scratch.row.bot_id,
                          }, {
                            onSuccess: () => {
                              onClose();
                              onActivateSurface({ kind: "primary" }, "switch");
                            },
                          });
                        }}
                        className="text-text-dim hover:text-text disabled:opacity-50"
                      >
                        Make primary
                      </button>
                    </div>
                  )}
                </div>
              </div>
            );
              })}
            </div>
          ))}
          {entries[activeIndex] && (
            <div className="border-t border-surface-border px-4 py-2 text-[11px] text-text-dim">
              {pickerMode === "split" ? "Enter adds split · Esc closes" : "Enter switches · Ctrl/Cmd+Enter splits · /split opens split mode"}
            </div>
          )}
          {deepSearchLoading && query.trim().length >= 2 && (
            <div className="px-4 py-2 text-[11px] text-text-dim">Searching message history...</div>
          )}
          {deepSearchError && (
            <div className="px-4 py-2 text-[11px] text-danger">
              {deepSearchError instanceof Error ? deepSearchError.message : "Deep search failed."}
            </div>
          )}
        </div>
      </div>
    </>,
    document.body,
  );
}
