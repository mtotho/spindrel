/**
 * Simple CSS hover-based tooltip for contextual help.
 */
import { HelpCircle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

interface Props {
  text: string;
  size?: number;
}

export function HelpTooltip({ text, size = 14 }: Props) {
  const t = useThemeTokens();

  return (
    <span
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        cursor: "help",
      }}
      className="help-tooltip-trigger"
    >
      <HelpCircle size={size} color={t.textDim} />
      <span
        className="help-tooltip-content"
        style={{
          position: "absolute",
          bottom: "calc(100% + 6px)",
          left: "50%",
          transform: "translateX(-50%)",
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6,
          padding: "6px 10px",
          fontSize: 11,
          lineHeight: 1.4,
          color: t.text,
          whiteSpace: "normal",
          width: 240,
          zIndex: 1000,
          boxShadow: `0 4px 12px ${t.overlayLight}`,
          pointerEvents: "none",
          opacity: 0,
          transition: "opacity 0.15s",
        }}
      >
        {text}
      </span>
      <style>{`
        .help-tooltip-trigger:hover .help-tooltip-content {
          opacity: 1 !important;
        }
      `}</style>
    </span>
  );
}
