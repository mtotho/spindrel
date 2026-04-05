import { X, AlertTriangle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useRestartServer } from "@/src/api/hooks/useServerOps";
import ReactDOM from "react-dom";

interface Props {
  onClose: () => void;
}

export function RestartConfirmModal({ onClose }: Props) {
  const t = useThemeTokens();
  const restartMut = useRestartServer();

  const handleRestart = () => {
    restartMut.mutate(undefined, {
      onSuccess: () => {
        // Keep modal open showing "restarting" state — server will drop connection
      },
    });
  };

  if (typeof document === "undefined") return null;

  return ReactDOM.createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={restartMut.isPending || restartMut.isSuccess ? undefined : onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 10020,
        }}
      />
      {/* Modal */}
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 420,
          maxWidth: "90vw",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          padding: 20,
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 16,
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
            Restart Server
          </span>
          {!restartMut.isPending && !restartMut.isSuccess && (
            <button
              onClick={onClose}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: 4,
                display: "flex",
                alignItems: "center",
              }}
            >
              <X size={16} color={t.textDim} />
            </button>
          )}
        </div>

        {restartMut.isSuccess ? (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, paddingTop: 16, paddingBottom: 16 }}>
            <div className="chat-spinner" />
            <span style={{ color: t.textMuted, fontSize: 13, textAlign: "center" }}>
              Server is restarting...
            </span>
            <span style={{ color: t.textDim, fontSize: 11, textAlign: "center" }}>
              The page will reconnect automatically when the server comes back up.
            </span>
          </div>
        ) : (
          <>
            {/* Warning */}
            <div
              style={{
                display: "flex",
                flexDirection: "row",
                gap: 10,
                backgroundColor: "rgba(245,158,11,0.08)",
                border: "1px solid rgba(245,158,11,0.25)",
                borderRadius: 8,
                padding: 12,
                marginBottom: 16,
              }}
            >
              <AlertTriangle
                size={15}
                color="#f59e0b"
                style={{ marginTop: 1, flexShrink: 0 }}
              />
              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
                <span
                  style={{ fontSize: 12, fontWeight: 600, color: "#f59e0b" }}
                >
                  This will interrupt active connections
                </span>
                <span
                  style={{ fontSize: 11, color: t.textMuted, lineHeight: "17px" }}
                >
                  The server will pull the latest code from git and restart via
                  systemd. All active agent runs and streaming connections will be
                  dropped.
                </span>
              </div>
            </div>

            {/* Actions */}
            <div
              style={{ display: "flex", flexDirection: "row", justifyContent: "flex-end", gap: 8 }}
            >
              <button
                onClick={onClose}
                disabled={restartMut.isPending}
                style={{
                  paddingLeft: 12,
                  paddingRight: 12,
                  paddingTop: 6,
                  paddingBottom: 6,
                  borderRadius: 6,
                  border: `1px solid ${t.surfaceBorder}`,
                  background: "none",
                  cursor: "pointer",
                  color: t.textDim,
                  fontSize: 12,
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleRestart}
                disabled={restartMut.isPending}
                style={{
                  paddingLeft: 12,
                  paddingRight: 12,
                  paddingTop: 6,
                  paddingBottom: 6,
                  borderRadius: 6,
                  backgroundColor: t.danger,
                  border: "none",
                  opacity: restartMut.isPending ? 0.5 : 1,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {restartMut.isPending ? (
                  <div className="chat-spinner" />
                ) : (
                  <span
                    style={{ fontSize: 12, fontWeight: 600, color: "#fff" }}
                  >
                    Restart Server
                  </span>
                )}
              </button>
            </div>

            {restartMut.isError && (
              <span
                style={{ color: t.danger, fontSize: 11, marginTop: 8, display: "block" }}
              >
                Failed to restart server. Check permissions and try again.
              </span>
            )}
          </>
        )}
      </div>
    </>,
    document.body
  );
}
