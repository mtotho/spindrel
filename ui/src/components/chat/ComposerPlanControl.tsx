import { useEffect, useRef } from "react";
import { ChevronDown, ListTodo } from "lucide-react";
import { createPortal } from "react-dom";
import { useThemeTokens } from "../../theme/tokens";
import { getComposerPlanControlState, type ComposerPlanMode, type ComposerPlanTone } from "./planControl";

type ComposerControlPresentation = "default" | "terminal";

interface ComposerPlanControlProps {
  enabled: boolean;
  presentation: ComposerControlPresentation;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  planMode: ComposerPlanMode;
  hasPlan: boolean;
  disabled?: boolean;
  planBusy?: boolean;
  onTogglePlanMode?: () => void;
  onApprovePlan?: () => void;
  terminalBorder: string;
  terminalFontStack: string;
}

export function ComposerPlanControl({
  enabled,
  presentation,
  open,
  onOpenChange,
  planMode,
  hasPlan,
  disabled = false,
  planBusy = false,
  onTogglePlanMode,
  onApprovePlan,
  terminalBorder,
  terminalFontStack,
}: ComposerPlanControlProps) {
  const t = useThemeTokens();
  const controlRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const isTerminalMode = presentation === "terminal";
  const state = getComposerPlanControlState({
    planMode,
    hasPlan,
    canApprovePlan: !!onApprovePlan && planMode === "planning",
  });
  const colors = planToneColors(t, state.tone);

  useEffect(() => {
    if (!open || !state.showMenu) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      const clickedTrigger = !!(controlRef.current && target && controlRef.current.contains(target));
      const clickedMenu = !!(menuRef.current && target && menuRef.current.contains(target));
      if (!clickedTrigger && !clickedMenu) {
        onOpenChange(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [onOpenChange, open, state.showMenu]);

  if (!enabled) return null;

  return (
    <div ref={controlRef} style={{ position: "relative", display: "flex", alignItems: "center", flexShrink: 0 }}>
      <button
        type="button"
        onMouseDown={(e) => {
          e.preventDefault();
          e.stopPropagation();
        }}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          if (state.showMenu) {
            onOpenChange(!open);
          } else {
            onOpenChange(false);
            onTogglePlanMode?.();
          }
        }}
        disabled={disabled || planBusy}
        title={state.title}
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "center",
          gap: 4,
          minHeight: isTerminalMode ? 22 : 24,
          padding: isTerminalMode ? "0 0 0 2px" : "4px 8px",
          border: isTerminalMode ? "none" : `1px solid ${colors.border}`,
          borderRadius: isTerminalMode ? 0 : 8,
          background: isTerminalMode ? "transparent" : colors.background,
          color: colors.text,
          cursor: disabled || planBusy ? "default" : "pointer",
          fontSize: 11,
          lineHeight: 1.2,
          whiteSpace: "nowrap",
          fontFamily: isTerminalMode ? terminalFontStack : undefined,
          opacity: disabled || planBusy ? 0.55 : 1,
          flexShrink: 0,
        }}
      >
        <ListTodo size={isTerminalMode ? 13 : 14} color={colors.icon} />
        <span>{state.label}</span>
        {state.showMenu && <ChevronDown size={12} color={colors.icon} />}
      </button>
      {open && state.showMenu && (() => {
        const rect = controlRef.current?.getBoundingClientRect();
        const dropdownWidth = 168;
        const dropdownLeft = isTerminalMode
          ? Math.max(12, (rect?.right ?? window.innerWidth - 16) - dropdownWidth)
          : Math.max(12, Math.min(rect?.left ?? 16, window.innerWidth - dropdownWidth - 12));
        const dropdownBottom = rect ? window.innerHeight - rect.top + 8 : 80;
        return createPortal(
          <>
            <div
              onClick={() => onOpenChange(false)}
              style={{ position: "fixed", inset: 0, zIndex: 50000 }}
            />
            <div
              ref={menuRef}
              style={{
                position: "fixed",
                bottom: dropdownBottom,
                left: dropdownLeft,
                width: isTerminalMode ? 136 : 156,
                background: isTerminalMode ? t.overlayLight : t.surfaceRaised,
                border: isTerminalMode ? `1px solid ${terminalBorder}` : `1px solid ${t.surfaceBorder}`,
                borderRadius: isTerminalMode ? 6 : 10,
                boxShadow: isTerminalMode ? "none" : "0 10px 24px rgba(0,0,0,0.14)",
                padding: isTerminalMode ? 2 : 4,
                zIndex: 50001,
              }}
            >
              <button
                type="button"
                onMouseDown={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                }}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onOpenChange(false);
                  onTogglePlanMode?.();
                }}
                style={menuItemStyle(t, isTerminalMode, terminalFontStack)}
              >
                {state.primaryActionLabel}
              </button>
              {state.canApprove && onApprovePlan && (
                <button
                  type="button"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                  }}
                  onClick={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    onOpenChange(false);
                    onApprovePlan();
                  }}
                  style={menuItemStyle(t, isTerminalMode, terminalFontStack)}
                >
                  Approve plan
                </button>
              )}
            </div>
          </>,
          document.body
        );
      })()}
    </div>
  );
}

function menuItemStyle(t: ReturnType<typeof useThemeTokens>, isTerminalMode: boolean, terminalFontStack: string) {
  return {
    width: "100%",
    display: "block",
    background: "transparent",
    border: "none",
    borderRadius: isTerminalMode ? 4 : 8,
    padding: isTerminalMode ? "6px 8px" : "8px 10px",
    color: isTerminalMode ? t.textMuted : t.text,
    fontSize: isTerminalMode ? 11 : 12,
    fontFamily: isTerminalMode ? terminalFontStack : undefined,
    textAlign: "left" as const,
    cursor: "pointer",
  };
}

function planToneColors(t: ReturnType<typeof useThemeTokens>, tone: ComposerPlanTone) {
  switch (tone) {
    case "warning":
      return {
        border: t.warningBorder,
        background: t.warningSubtle,
        text: t.warningMuted,
        icon: t.warning,
      };
    case "danger":
      return {
        border: t.dangerBorder,
        background: t.dangerSubtle,
        text: t.dangerMuted,
        icon: t.danger,
      };
    case "success":
      return {
        border: t.successBorder,
        background: t.successSubtle,
        text: t.success,
        icon: t.success,
      };
    case "neutral":
    default:
      return {
        border: "transparent",
        background: "transparent",
        text: t.textMuted,
        icon: t.textDim,
      };
  }
}
