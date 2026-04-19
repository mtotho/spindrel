// Sparkles chip: shows the count of skills currently in context.
// Click opens the shared SkillsInContextPanel.
// Mobile-header placement is the primary caller today — composer uses the + menu instead.

import { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { Sparkles } from "lucide-react";

import { useThemeTokens } from "../../theme/tokens";
import { SkillsInContextPanel, useSkillsInContext } from "./SkillsInContextPanel";

interface ContextChipProps {
  channelId?: string;
  composerText?: string;
  botId?: string;
  onInsertSkillTag?: (skillId: string) => void;
  size?: number;
  hideWhenEmpty?: boolean;
  compact?: boolean;
  placement?: "above" | "below";
}

export function ContextChip({
  channelId,
  composerText = "",
  botId,
  onInsertSkillTag,
  size = 36,
  hideWhenEmpty = false,
  compact = false,
  placement = "above",
}: ContextChipProps) {
  const t = useThemeTokens();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top?: number; bottom?: number; left: number }>({ bottom: 0, left: 0 });

  const { count } = useSkillsInContext({ channelId, composerText });
  const empty = count === 0;

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        triggerRef.current && !triggerRef.current.contains(target) &&
        popoverRef.current && !popoverRef.current.contains(target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  const togglePopover = () => {
    if (!triggerRef.current) {
      setOpen((v) => !v);
      return;
    }
    const rect = triggerRef.current.getBoundingClientRect();
    const width = compact ? Math.min(window.innerWidth - 16, 420) : 360;
    const left = compact
      ? Math.max(8, (window.innerWidth - width) / 2)
      : Math.max(12, Math.min(rect.left - width + rect.width, window.innerWidth - width - 12));
    if (placement === "below") {
      setPos({ top: rect.bottom + 8, left });
    } else {
      setPos({ bottom: window.innerHeight - rect.top + 8, left });
    }
    setOpen((v) => !v);
  };

  if (empty && hideWhenEmpty) return null;

  return (
    <>
      <button
        ref={triggerRef}
        className="input-action-btn"
        onClick={togglePopover}
        aria-label={
          empty
            ? "No skills currently in context. Click to drop one in."
            : `${count} skill${count === 1 ? "" : "s"} in context. Click for details.`
        }
        aria-expanded={open}
        title={
          empty
            ? "No skills loaded — click to drop one in"
            : `${count} skill${count === 1 ? "" : "s"} in context`
        }
        style={{
          width: size,
          height: size,
          flexShrink: 0,
          opacity: empty ? 0.5 : 1,
          position: "relative",
        }}
      >
        <Sparkles
          size={16}
          color={empty ? t.textDim : t.purple}
          strokeWidth={empty ? 2 : 2.5}
        />
        {!empty && (
          <span
            style={{
              position: "absolute",
              top: 2,
              right: 2,
              minWidth: 14,
              height: 14,
              padding: "0 3px",
              borderRadius: 7,
              background: t.purple,
              color: "#fff",
              fontSize: 9,
              fontWeight: 700,
              lineHeight: "14px",
              textAlign: "center",
            }}
          >
            {count}
          </span>
        )}
      </button>

      {open &&
        ReactDOM.createPortal(
          <div
            ref={popoverRef}
            role="dialog"
            aria-label="Skills in context"
            className="fixed z-[10000] flex flex-col rounded-lg border shadow-xl"
            style={{
              top: pos.top,
              bottom: pos.bottom,
              left: pos.left,
              width: compact ? Math.min(window.innerWidth - 16, 420) : 360,
              maxHeight: compact ? "min(60vh, 520px)" : "min(480px, 75vh)",
              backgroundColor: t.surfaceRaised,
              borderColor: t.surfaceBorder,
            }}
          >
            <SkillsInContextPanel
              channelId={channelId}
              composerText={composerText}
              botId={botId}
              onInsertSkillTag={onInsertSkillTag}
              onClose={() => setOpen(false)}
            />
          </div>,
          document.body,
        )}
    </>
  );
}
