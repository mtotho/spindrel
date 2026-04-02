/**
 * Inline overlay that replaces the textarea during audio recording.
 * Displays a pulsing red dot, duration timer, and cancel button.
 */
import { Pressable } from "react-native";
import { X } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";

interface Props {
  durationMs: number;
  onCancel: () => void;
  isMobile: boolean;
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function RecordingOverlay({ durationMs, onCancel, isMobile }: Props) {
  const t = useThemeTokens();

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: isMobile ? "8px 12px" : "10px 16px",
        borderRadius: 10,
        border: `1px solid #ef4444`,
        background: t.surfaceRaised,
        minHeight: isMobile ? 36 : 44,
      }}
    >
      {/* Pulsing red dot */}
      <div
        style={{
          width: 10,
          height: 10,
          borderRadius: 5,
          backgroundColor: "#ef4444",
          animation: "pulse-dot 1.2s ease-in-out infinite",
          flexShrink: 0,
        }}
      />

      {/* Duration */}
      <span
        style={{
          fontSize: 15,
          fontVariantNumeric: "tabular-nums",
          color: t.text,
          flex: 1,
        }}
      >
        Recording {formatDuration(durationMs)}
      </span>

      {/* Cancel button */}
      <Pressable
        onPress={onCancel}
        style={{
          width: 28,
          height: 28,
          borderRadius: 14,
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
        className="hover:bg-surface-overlay active:bg-surface-overlay"
      >
        <X size={16} color={t.textDim} />
      </Pressable>

      {/* Keyframe animation for the pulsing dot */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.4; transform: scale(0.8); }
        }
      `}</style>
    </div>
  );
}
