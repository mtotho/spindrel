import { useThemeTokens } from "../../theme/tokens";
import {
  getHarnessApprovalModeControlState,
  type HarnessApprovalMode,
  type HarnessApprovalModeTone,
} from "./harnessApprovalModeControl";

type ComposerControlPresentation = "default" | "terminal";

interface ComposerApprovalModeControlProps {
  presentation: ComposerControlPresentation;
  mode: HarnessApprovalMode | string | null | undefined;
  disabled?: boolean;
  mutating?: boolean;
  onCycle?: () => void;
  terminalFontStack: string;
}

export function ComposerApprovalModeControl({
  presentation,
  mode,
  disabled = false,
  mutating = false,
  onCycle,
  terminalFontStack,
}: ComposerApprovalModeControlProps) {
  const t = useThemeTokens();
  if (!onCycle) return null;

  const isTerminalMode = presentation === "terminal";
  const state = getHarnessApprovalModeControlState(mode);
  const colors = harnessApprovalModeToneColors(t, state.tone);
  const isDisabled = disabled || mutating;

  return (
    <button
      type="button"
      onMouseDown={(e) => {
        e.preventDefault();
        e.stopPropagation();
      }}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onCycle();
      }}
      disabled={isDisabled}
      title={state.title}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        minHeight: isTerminalMode ? 22 : 24,
        padding: isTerminalMode ? "0 2px" : "4px 4px",
        border: "none",
        borderRadius: 0,
        background: "transparent",
        color: colors.text,
        cursor: isDisabled ? "default" : "pointer",
        fontSize: isTerminalMode ? 11.5 : 11,
        lineHeight: 1.2,
        whiteSpace: "nowrap",
        fontFamily: isTerminalMode ? terminalFontStack : undefined,
        fontWeight: isTerminalMode ? 500 : 600,
        textTransform: "lowercase",
        opacity: isDisabled ? 0.55 : 1,
        flexShrink: 0,
      }}
    >
      {state.label}
    </button>
  );
}

function harnessApprovalModeToneColors(
  t: ReturnType<typeof useThemeTokens>,
  tone: HarnessApprovalModeTone,
) {
  switch (tone) {
    case "success":
      return { text: t.success };
    case "warning":
      return { text: t.warningMuted };
    case "plan":
      return { text: t.accent };
    case "neutral":
    default:
      return { text: t.textDim };
  }
}
