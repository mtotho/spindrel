import { useState } from "react";
import { ChevronDown, Clock, Info, MoreHorizontal, Search, X } from "lucide-react";
import {
  compactSessionId,
  formatSessionSurfaceLabel,
  type SessionResumeMetadata,
} from "@/src/lib/sessionResume";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

interface SessionResumeCardProps {
  metadata: SessionResumeMetadata;
  onDismiss: () => void;
  onHideChannel?: () => void;
  onHideGlobal: () => void;
  onOpenSessions?: () => void;
  chatMode?: "default" | "terminal";
}

function formatDateTime(value?: string | null): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function countsLine(metadata: SessionResumeMetadata): string {
  const bits = [];
  if (typeof metadata.messageCount === "number") bits.push(`${metadata.messageCount} msgs`);
  if (typeof metadata.sectionCount === "number") bits.push(`${metadata.sectionCount} sections`);
  if (metadata.botName) bits.push(metadata.botName);
  if (metadata.botModel) bits.push(metadata.botModel);
  return bits.join(" · ");
}

export function SessionResumeCard({
  metadata,
  onDismiss,
  onHideChannel,
  onHideGlobal,
  onOpenSessions,
  chatMode = "default",
}: SessionResumeCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const title = metadata.title?.trim() || formatSessionSurfaceLabel(metadata.surfaceKind);
  const isTerminal = chatMode === "terminal";
  const fontStyle = isTerminal ? { fontFamily: TERMINAL_FONT_STACK } : undefined;

  return (
    <div
      className="mb-3 rounded-md bg-surface-raised/70 px-3 py-2 text-xs text-text-muted"
      style={fontStyle}
    >
      <div className="flex items-start gap-2">
        <div className="mt-0.5 text-text-dim">
          <Clock size={14} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-medium text-text truncate">{title}</span>
            <span className="text-[10px] uppercase tracking-[0.08em] text-text-dim/80">
              {formatSessionSurfaceLabel(metadata.surfaceKind)}
            </span>
          </div>
          <div className="mt-1 text-text-dim">
            Last message {formatDateTime(metadata.lastVisibleMessageAt)}
          </div>
          <div className="mt-0.5 text-text-dim">
            Created {formatDateTime(metadata.createdAt)}
            {countsLine(metadata) ? ` · ${countsLine(metadata)}` : ""}
          </div>
          {expanded && (
            <div className="mt-2 space-y-1 text-text-dim">
              <div>Session {compactSessionId(metadata.sessionId)}</div>
              {metadata.lastActiveAt && metadata.lastActiveAt !== metadata.lastVisibleMessageAt && (
                <div>Last activity {formatDateTime(metadata.lastActiveAt)}</div>
              )}
              {metadata.summary && (
                <div className="text-text-muted">{metadata.summary}</div>
              )}
            </div>
          )}
        </div>
        <div className="relative flex items-center gap-0.5">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            title={expanded ? "Hide session details" : "Show session details"}
            className="rounded p-1 text-text-dim hover:bg-surface-overlay/60 hover:text-text"
          >
            <ChevronDown size={14} className={expanded ? "rotate-180 transition-transform" : "transition-transform"} />
          </button>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            title="Resume card options"
            className="rounded p-1 text-text-dim hover:bg-surface-overlay/60 hover:text-text"
          >
            <MoreHorizontal size={14} />
          </button>
          <button
            type="button"
            onClick={onDismiss}
            title="Dismiss until this session changes"
            className="rounded p-1 text-text-dim hover:bg-surface-overlay/60 hover:text-text"
          >
            <X size={14} />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-7 z-20 min-w-44 rounded-md bg-surface-overlay p-1 text-xs text-text-muted">
              {onOpenSessions && (
                <button
                  type="button"
                  onClick={() => {
                    onOpenSessions();
                    setMenuOpen(false);
                  }}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-surface-raised hover:text-text"
                >
                  <Search size={12} />
                  Open session picker
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  onDismiss();
                  setMenuOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-surface-raised hover:text-text"
              >
                <Info size={12} />
                Dismiss for now
              </button>
              {onHideChannel && (
                <button
                  type="button"
                  onClick={() => {
                    onHideChannel();
                    setMenuOpen(false);
                  }}
                  className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface-raised hover:text-text"
                >
                  Hide in this channel
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  onHideGlobal();
                  setMenuOpen(false);
                }}
                className="block w-full rounded px-2 py-1.5 text-left hover:bg-surface-raised hover:text-text"
              >
                Hide everywhere
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
