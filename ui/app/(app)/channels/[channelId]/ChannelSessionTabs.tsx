import { useEffect, useMemo, useState } from "react";
import { Search, StickyNote, X } from "lucide-react";
import {
  buildChannelSessionPickerEntries,
  buildChannelSessionPickerGroups,
  surfaceKey,
  type ChannelSessionActivationIntent,
  type ChannelSessionSurface,
  type ChannelSessionTabItem,
} from "@/src/lib/channelSessionSurfaces";
import {
  useChannelSessionCatalog,
  useChannelSessionSearch,
} from "@/src/api/hooks/useChannelSessions";

interface ChannelSessionTabStripProps {
  tabs: ChannelSessionTabItem[];
  onSelect: (surface: ChannelSessionSurface) => void;
  onClose: (tab: ChannelSessionTabItem) => void;
  onOpenSessions?: () => void;
}

export function ChannelSessionTabStrip({
  tabs,
  onSelect,
  onClose,
  onOpenSessions,
}: ChannelSessionTabStripProps) {
  if (tabs.length === 0) return null;
  return (
    <div
      data-testid="channel-session-tab-strip"
      className="flex h-9 shrink-0 items-center gap-1 overflow-x-auto px-3 pb-1 text-[12px]"
    >
      {tabs.map((tab) => (
        <div
          key={tab.key}
          data-testid="channel-session-tab"
          data-session-tab-key={tab.key}
          data-active={tab.active ? "true" : "false"}
          data-primary={tab.primary ? "true" : "false"}
          title={[tab.label, tab.meta].filter(Boolean).join("\n")}
          className={[
            "group relative flex h-8 max-w-[240px] shrink-0 items-center gap-1.5 rounded-md px-2.5 text-left transition-colors",
            tab.active
              ? "bg-accent/[0.08] text-text"
              : "text-text-muted hover:bg-surface-overlay/60 hover:text-text",
          ].join(" ")}
        >
          <button
            type="button"
            onClick={() => onSelect(tab.surface)}
            className="flex min-w-0 flex-1 items-center gap-1.5 bg-transparent text-left"
          >
            {tab.primary && (
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent/80" aria-hidden="true" />
            )}
            <span className="min-w-0 truncate">{tab.label}</span>
            {tab.meta && (
              <span className="hidden shrink-0 text-[10px] uppercase tracking-[0.08em] text-text-dim lg:inline">
                {tab.primary ? "Primary" : tab.surface.kind === "scratch" ? "Scratch" : "Session"}
              </span>
            )}
          </button>
          <span
            className={[
              "absolute inset-x-2 bottom-0 h-px rounded-full transition-colors",
              tab.active ? "bg-accent/80" : "bg-transparent",
            ].join(" ")}
            aria-hidden="true"
          />
          <button
            type="button"
            aria-label={`Close ${tab.label} tab`}
            title="Close tab"
            onClick={(event) => {
              event.stopPropagation();
              onClose(tab);
            }}
            className="ml-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-text-dim opacity-70 transition-colors hover:bg-surface-overlay hover:text-text group-hover:opacity-100"
          >
            <X size={12} />
          </button>
        </div>
      ))}
      {onOpenSessions && (
        <button
          type="button"
          onClick={onOpenSessions}
          className="ml-1 flex h-8 shrink-0 items-center rounded-md px-2 text-[11px] text-text-dim transition-colors hover:bg-surface-overlay/60 hover:text-text"
        >
          More
        </button>
      )}
    </div>
  );
}

interface ChannelSessionInlinePickerProps {
  channelId: string;
  channelLabel?: string | null;
  selectedSessionId?: string | null;
  onActivateSurface: (surface: ChannelSessionSurface, intent: ChannelSessionActivationIntent) => void;
  onOpenSessions?: () => void;
  onUnhideSurface?: (surface: ChannelSessionSurface) => void;
}

export function ChannelSessionInlinePicker({
  channelId,
  channelLabel,
  selectedSessionId,
  onActivateSurface,
  onOpenSessions,
  onUnhideSurface,
}: ChannelSessionInlinePickerProps) {
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const { data: channelSessions, isLoading, error } = useChannelSessionCatalog(channelId);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const {
    data: deepMatches,
    isFetching: deepSearchLoading,
    error: deepSearchError,
  } = useChannelSessionSearch(channelId, debouncedQuery);

  const entries = useMemo(
    () =>
      buildChannelSessionPickerEntries({
        channelLabel,
        selectedSessionId,
        channelSessions,
        deepMatches,
        query,
      }),
    [channelLabel, channelSessions, deepMatches, query, selectedSessionId],
  );
  const groups = useMemo(
    () => buildChannelSessionPickerGroups(entries, query),
    [entries, query],
  );

  return (
    <div
      data-testid="channel-session-inline-picker"
      className="flex min-h-0 flex-1 items-center justify-center bg-surface px-6 py-8"
    >
      <div className="flex w-full max-w-2xl flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold text-text">Choose a session</div>
            <div className="mt-1 text-[12px] text-text-dim">
              Closed tabs stay in history. Pick a recent session to bring it back.
            </div>
          </div>
          {onOpenSessions && (
            <button
              type="button"
              onClick={onOpenSessions}
              className="shrink-0 rounded-md px-3 py-1.5 text-[12px] font-medium text-accent transition-colors hover:bg-accent/[0.08]"
            >
              Full picker
            </button>
          )}
        </div>
        <label className="flex h-10 items-center gap-2 rounded-md bg-input px-3 text-sm text-text">
          <Search size={15} className="text-text-dim" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search recent sessions..."
            className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-text-dim"
          />
        </label>
        <div className="min-h-[220px] overflow-hidden rounded-md bg-surface-raised/35">
          {isLoading && <div className="px-4 py-8 text-sm text-text-dim">Loading sessions...</div>}
          {error && (
            <div className="px-4 py-8 text-sm text-danger">
              {error instanceof Error ? error.message : "Failed to load sessions."}
            </div>
          )}
          {!isLoading && !error && entries.length === 0 && (
            <div className="px-4 py-8 text-sm text-text-dim">No sessions matched that search.</div>
          )}
          {!isLoading && !error && groups.map((group) => (
            <div key={group.id} className="py-1">
              {groups.length > 1 && (
                <div className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
                  {group.label}
                </div>
              )}
              {group.entries.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  data-testid="channel-session-inline-row"
                  data-session-row-key={surfaceKey(entry.surface)}
                  onClick={() => {
                    onUnhideSurface?.(entry.surface);
                    onActivateSurface(entry.surface, "switch");
                  }}
                  className="mx-1 flex w-[calc(100%-0.5rem)] items-start gap-3 rounded-md px-3 py-2 text-left transition-colors hover:bg-surface-overlay/60"
                >
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-overlay text-text-dim">
                    <StickyNote size={14} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-medium text-text">{entry.label}</span>
                    <span className="mt-0.5 block truncate text-[11px] text-text-dim">{entry.meta}</span>
                    {entry.matches && entry.matches.length > 0 && (
                      <span className="mt-1 block space-y-1">
                        {entry.matches.slice(0, 2).map((match, idx) => (
                          <span
                            key={`${match.kind}:${match.message_id ?? match.section_id ?? idx}`}
                            className="block truncate text-[11px] text-text-muted"
                          >
                            {match.kind === "section" ? "Section" : "Message"}: {match.preview}
                          </span>
                        ))}
                      </span>
                    )}
                  </span>
                  {entry.selected && (
                    <span className="shrink-0 rounded-full bg-accent/10 px-1.5 py-0.5 text-[10px] font-medium text-accent">
                      Current
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
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
    </div>
  );
}
