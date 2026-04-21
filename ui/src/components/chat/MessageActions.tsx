/**
 * Message action buttons (copy, view trace) and avatar component.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useEffect, useRef, useState } from "react";
import { Copy, Check, Activity, Cog, FileText, MessageCircle } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { createPortal } from "react-dom";
import { writeToClipboard } from "../../utils/clipboard";
import type { ThemeTokens } from "../../theme/tokens";

// ---------------------------------------------------------------------------
// Copy + trace buttons -- appears on hover (web only)
// ---------------------------------------------------------------------------

export function MessageActions({
  text,
  fullTurnText,
  correlationId,
  t,
  canReplyInThread,
  onReplyInThread,
}: {
  text: string;
  /** Concatenated text of all segments in a multi-segment bot turn */
  fullTurnText?: string;
  correlationId?: string;
  t: ThemeTokens;
  /** Show the Reply-in-thread button. Callers gate this to false inside
   *  thread / ephemeral views (UI-only nested-thread guard). */
  canReplyInThread?: boolean;
  /** Click handler for the Reply-in-thread button. */
  onReplyInThread?: () => void;
}) {
  const [copied, setCopied] = useState<"single" | "full" | false>(false);
  const navigate = useNavigate();

  const btnStyle = (active?: boolean): React.CSSProperties => ({
    display: "flex", flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    width: 28,
    height: 28,
    borderRadius: 6,
    border: `1px solid ${t.surfaceBorder}`,
    backgroundColor: t.surfaceRaised,
    color: active ? "#10b981" : t.textMuted,
    cursor: "pointer",
    padding: 0,
    boxShadow: "0 1px 4px rgba(0,0,0,0.15)",
  });

  const doCopy = (value: string, which: "single" | "full") => {
    writeToClipboard(value).then(() => {
      setCopied(which);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="msg-actions" style={{ userSelect: "none" }}>
      {canReplyInThread && onReplyInThread && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onReplyInThread();
          }}
          title="Reply in thread"
          style={btnStyle()}
        >
          <MessageCircle size={14} />
        </button>
      )}
      {correlationId && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/admin/logs/${correlationId}`);
          }}
          title="View trace"
          style={btnStyle()}
        >
          <Activity size={14} />
        </button>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation();
          doCopy(fullTurnText || text, fullTurnText ? "full" : "single");
        }}
        title={fullTurnText ? "Copy full response" : "Copy message"}
        style={btnStyle(!!copied)}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TimestampActions — tap the timestamp to reveal a small popover of actions.
//
// Works on any platform (mobile-critical: desktop has the hover bar already,
// but this gives mobile users and desktop-keyboard users an alternate path).
// Semantically the timestamp IS trace metadata, so tapping it for more
// metadata (trace + copy + bot info) is aligned.
// ---------------------------------------------------------------------------

export interface TimestampActionsProps {
  timestamp: string;
  text: string;
  /** Concatenated text of all segments in a multi-segment bot turn */
  fullTurnText?: string;
  correlationId?: string;
  /** When defined, this is a bot message and "View bot info" becomes available */
  onBotClick?: () => void;
  t: ThemeTokens;
}

export function TimestampActions({
  timestamp,
  text,
  fullTurnText,
  correlationId,
  onBotClick,
  t,
}: TimestampActionsProps) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState<"single" | "full" | false>(false);
  const anchorRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  // Position popover on open
  useEffect(() => {
    if (!open || !anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    // Popover is anchored below-left of timestamp; clamp to viewport
    const POPOVER_W = 200;
    const margin = 8;
    let left = rect.left;
    if (left + POPOVER_W + margin > window.innerWidth) {
      left = window.innerWidth - POPOVER_W - margin;
    }
    if (left < margin) left = margin;
    setPosition({ top: rect.bottom + 4, left });
  }, [open]);

  // Dismiss on outside click / Escape / scroll (anchor moves)
  useEffect(() => {
    if (!open) return;
    const clickHandler = (e: MouseEvent) => {
      const tgt = e.target as Node;
      if (popoverRef.current?.contains(tgt)) return;
      if (anchorRef.current?.contains(tgt)) return;
      setOpen(false);
    };
    const keyHandler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const scrollHandler = () => setOpen(false);
    document.addEventListener("mousedown", clickHandler);
    document.addEventListener("keydown", keyHandler);
    window.addEventListener("scroll", scrollHandler, true);
    return () => {
      document.removeEventListener("mousedown", clickHandler);
      document.removeEventListener("keydown", keyHandler);
      window.removeEventListener("scroll", scrollHandler, true);
    };
  }, [open]);

  const doCopy = (value: string, which: "single" | "full") => {
    writeToClipboard(value).then(() => {
      setCopied(which);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const hasFullTurn = !!fullTurnText && fullTurnText !== text && fullTurnText.length > text.length;
  const nothingToShow = !correlationId && !onBotClick && !text;
  if (nothingToShow) {
    return (
      <span style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {timestamp}
      </span>
    );
  }

  const popover = open && position
    ? createPortal(
        <div
          ref={popoverRef}
          role="menu"
          className="flex flex-col py-1 rounded-md"
          style={{
            position: "fixed",
            top: position.top,
            left: position.left,
            width: 200,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
            zIndex: 10040,
          }}
        >
          {correlationId && (
            <MenuItem
              icon={<Activity size={14} />}
              label="View trace"
              t={t}
              onClick={() => {
                setOpen(false);
                navigate(`/admin/logs/${correlationId}`);
              }}
            />
          )}
          {text && (
            <MenuItem
              icon={copied === "single" ? <Check size={14} color="#10b981" /> : <Copy size={14} />}
              label={copied === "single" ? "Copied!" : "Copy message"}
              t={t}
              onClick={() => doCopy(text, "single")}
            />
          )}
          {hasFullTurn && (
            <MenuItem
              icon={copied === "full" ? <Check size={14} color="#10b981" /> : <FileText size={14} />}
              label={copied === "full" ? "Copied!" : "Copy full response"}
              t={t}
              onClick={() => doCopy(fullTurnText!, "full")}
            />
          )}
          {onBotClick && (
            <MenuItem
              icon={<Cog size={14} />}
              label="View bot context"
              t={t}
              onClick={() => {
                setOpen(false);
                onBotClick();
              }}
            />
          )}
        </div>,
        document.body,
      )
    : null;

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Message actions"
        className="timestamp-trigger"
        style={{
          background: "transparent",
          border: "none",
          padding: 0,
          margin: 0,
          cursor: "pointer",
          fontSize: 10,
          color: open ? t.text : t.textDim,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          borderBottom: `1px dotted ${open ? t.textMuted : "transparent"}`,
          transition: "color 0.15s, border-color 0.15s",
        }}
      >
        {timestamp}
      </button>
      {popover}
    </>
  );
}

function MenuItem({
  icon,
  label,
  t,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  t: ThemeTokens;
  onClick: () => void;
}) {
  const [hover, setHover] = useState(false);
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="flex items-center gap-2 px-3 py-2 text-left border-0 cursor-pointer"
      style={{
        background: hover ? t.surfaceOverlay : "transparent",
        color: t.text,
        fontSize: 12,
      }}
    >
      <span className="flex items-center justify-center shrink-0" style={{ width: 16, color: t.textMuted }}>
        {icon}
      </span>
      <span>{label}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Avatar
// ---------------------------------------------------------------------------

export function Avatar({ name, isUser, onClick, size = 36 }: { name: string; isUser: boolean; onClick?: () => void; size?: number }) {
  const bg = isUser ? "#4b5563" : avatarColorLocal(name);
  const letter = isUser ? "U" : (name[0] || "B").toUpperCase();
  const clickable = !isUser && !!onClick;
  const fontSize = size <= 24 ? 11 : 14;
  const radius = size <= 24 ? 4 : 6;

  return (
    <div
      onClick={clickable ? onClick : undefined}
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        backgroundColor: bg,
        display: "flex", flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
        userSelect: "none",
        cursor: clickable ? "pointer" : undefined,
      }}
    >
      <span style={{ color: "#fff", fontSize, fontWeight: 700 }}>
        {letter}
      </span>
    </div>
  );
}

// Local copy to keep this file self-contained
function avatarColorLocal(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#06b6d4", "#ef4444", "#e879f9",
  ];
  return colors[Math.abs(hash) % colors.length];
}
