import { AlertTriangle, Send, Lock, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import type { SecretCheckResult } from "@/src/api/hooks/useSecretCheck";

interface SecretWarningDialogProps {
  result: SecretCheckResult;
  onSendAnyway: () => void;
  onCancel: () => void;
  onAddToSecrets: () => void;
}

export function SecretWarningDialog({
  result,
  onSendAnyway,
  onCancel,
  onAddToSecrets,
}: SecretWarningDialogProps) {
  const t = useThemeTokens();

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
      onClick={onCancel}
    >
      <div
        style={{
          background: t.surface,
          borderRadius: 12,
          padding: 24,
          width: "100%",
          maxWidth: 440,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <AlertTriangle size={20} color={t.warning} />
          <span style={{ fontSize: 16, fontWeight: 600, color: t.text }}>
            Possible secret detected
          </span>
        </div>

        <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.5 }}>
          Your message appears to contain a secret or credential. Secrets sent in
          chat are visible to the LLM provider and may be stored in conversation history.
        </div>

        {result.exact_matches > 0 && (
          <div
            style={{
              padding: "8px 12px",
              borderRadius: 6,
              background: t.dangerSubtle,
              fontSize: 12,
              color: t.danger,
            }}
          >
            Matched {result.exact_matches} known server secret(s)
          </div>
        )}

        {result.pattern_matches.length > 0 && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              padding: "8px 12px",
              borderRadius: 6,
              background: t.warningSubtle,
              fontSize: 12,
              color: t.warning,
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 2 }}>Pattern matches:</div>
            {result.pattern_matches.map((pm, i) => (
              <div key={i}>{pm.type}</div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button
            onClick={onCancel}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: `1px solid ${t.surfaceOverlay}`,
              background: "transparent",
              color: t.text,
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            <X size={14} style={{ marginRight: 4 }} />
            Cancel
          </button>
          <button
            onClick={onAddToSecrets}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: `1px solid ${t.surfaceOverlay}`,
              background: "transparent",
              color: t.accent,
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            <Lock size={14} style={{ marginRight: 4 }} />
            Add to Secrets
          </button>
          <button
            onClick={onSendAnyway}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: "none",
              background: t.warning,
              color: "#fff",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
            }}
          >
            <Send size={14} style={{ marginRight: 4 }} />
            Send Anyway
          </button>
        </div>
      </div>
    </div>
  );
}
