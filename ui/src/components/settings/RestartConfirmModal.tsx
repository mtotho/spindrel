import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { X, AlertTriangle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useRestartServer } from "@/src/api/hooks/useServerOps";

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

  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const ReactDOM = require("react-dom");
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
        <View
          style={{
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 16,
          }}
        >
          <Text style={{ fontSize: 14, fontWeight: "700", color: t.text }}>
            Restart Server
          </Text>
          {!restartMut.isPending && !restartMut.isSuccess && (
            <Pressable onPress={onClose} hitSlop={8}>
              <X size={16} color={t.textDim} />
            </Pressable>
          )}
        </View>

        {restartMut.isSuccess ? (
          <View style={{ alignItems: "center", gap: 12, paddingVertical: 16 }}>
            <ActivityIndicator size="large" color={t.accent} />
            <Text style={{ color: t.textMuted, fontSize: 13, textAlign: "center" }}>
              Server is restarting...
            </Text>
            <Text style={{ color: t.textDim, fontSize: 11, textAlign: "center" }}>
              The page will reconnect automatically when the server comes back up.
            </Text>
          </View>
        ) : (
          <>
            {/* Warning */}
            <View
              style={{
                flexDirection: "row",
                gap: 10,
                backgroundColor: "rgba(245,158,11,0.08)",
                borderWidth: 1,
                borderColor: "rgba(245,158,11,0.25)",
                borderRadius: 8,
                padding: 12,
                marginBottom: 16,
              }}
            >
              <AlertTriangle
                size={15}
                color="#f59e0b"
                style={{ marginTop: 1, flexShrink: 0 } as any}
              />
              <View style={{ flex: 1, gap: 4 }}>
                <Text
                  style={{ fontSize: 12, fontWeight: "600", color: "#f59e0b" }}
                >
                  This will interrupt active connections
                </Text>
                <Text
                  style={{ fontSize: 11, color: t.textMuted, lineHeight: 17 }}
                >
                  The server will pull the latest code from git and restart via
                  systemd. All active agent runs and streaming connections will be
                  dropped.
                </Text>
              </View>
            </View>

            {/* Actions */}
            <View
              style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8 }}
            >
              <Pressable
                onPress={onClose}
                disabled={restartMut.isPending}
                style={{
                  paddingHorizontal: 12,
                  paddingVertical: 6,
                  borderRadius: 6,
                  borderWidth: 1,
                  borderColor: t.surfaceBorder,
                }}
              >
                <Text style={{ fontSize: 12, color: t.textDim }}>Cancel</Text>
              </Pressable>
              <Pressable
                onPress={handleRestart}
                disabled={restartMut.isPending}
                style={{
                  paddingHorizontal: 12,
                  paddingVertical: 6,
                  borderRadius: 6,
                  backgroundColor: t.danger,
                  opacity: restartMut.isPending ? 0.5 : 1,
                }}
              >
                {restartMut.isPending ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text
                    style={{ fontSize: 12, fontWeight: "600", color: "#fff" }}
                  >
                    Restart Server
                  </Text>
                )}
              </Pressable>
            </View>

            {restartMut.isError && (
              <Text
                style={{ color: t.danger, fontSize: 11, marginTop: 8 }}
              >
                Failed to restart server. Check permissions and try again.
              </Text>
            )}
          </>
        )}
      </div>
    </>,
    document.body
  );
}
