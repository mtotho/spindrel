import { useState } from "react";
import { View, Text, ActivityIndicator } from "react-native";
import { RefreshCw, ExternalLink } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSystemStatus } from "@/src/api/hooks/useSystemStatus";
import { useVersion } from "@/src/api/hooks/useVersion";
import { useCheckUpdate, useTogglePause } from "@/src/api/hooks/useServerOps";
import {
  ActionButton,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { RestartConfirmModal } from "./RestartConfirmModal";

export function ServerStatusBar() {
  const t = useThemeTokens();
  const { data: status } = useSystemStatus();
  const { data: version } = useVersion();
  const checkUpdate = useCheckUpdate();
  const togglePause = useTogglePause();
  const [showRestartModal, setShowRestartModal] = useState(false);

  const paused = status?.paused ?? false;

  return (
    <>
      <View
        style={{
          backgroundColor: t.surfaceRaised,
          borderRadius: 10,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          padding: 14,
          gap: 10,
        }}
      >
        {/* Row 1: Status + controls */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          {/* Status indicator */}
          <View
            style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
          >
            <View
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                backgroundColor: paused ? t.warning : t.success,
              }}
            />
            <StatusBadge
              label={paused ? "Paused" : "Running"}
              variant={paused ? "warning" : "success"}
            />
          </View>

          <View style={{ flex: 1 }} />

          {/* Pause/Resume */}
          <ActionButton
            label={
              togglePause.isPending
                ? "..."
                : paused
                  ? "Resume"
                  : "Pause"
            }
            onPress={() => togglePause.mutate(!paused)}
            variant={paused ? "primary" : "secondary"}
            size="small"
            disabled={togglePause.isPending}
          />

          {/* Restart */}
          <ActionButton
            label="Restart"
            onPress={() => setShowRestartModal(true)}
            variant="danger"
            size="small"
            icon={<RefreshCw size={12} />}
          />
        </View>

        {/* Row 2: Version + update check */}
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <Text style={{ color: t.textDim, fontSize: 12, fontFamily: "monospace" }}>
            Spindrel v{version ?? "..."}
            {checkUpdate.data?.git_hash
              ? ` (${checkUpdate.data.git_hash})`
              : ""}
          </Text>

          <View style={{ flex: 1 }} />

          {/* Update check result */}
          {checkUpdate.data && !checkUpdate.isFetching && (
            checkUpdate.data.update_available ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <StatusBadge label={`v${checkUpdate.data.latest} available`} variant="info" />
                {checkUpdate.data.latest_url && (
                  <a
                    href={checkUpdate.data.latest_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ display: "flex", alignItems: "center" }}
                  >
                    <ExternalLink size={12} color={t.accent} />
                  </a>
                )}
              </View>
            ) : checkUpdate.data.error ? (
              <Text style={{ color: t.textDim, fontSize: 11 }}>
                Check failed
              </Text>
            ) : (
              <Text style={{ color: t.success, fontSize: 11 }}>
                Up to date
              </Text>
            )
          )}

          {checkUpdate.isFetching && (
            <ActivityIndicator size="small" color={t.accent} />
          )}

          <ActionButton
            label="Check for Update"
            onPress={() => checkUpdate.refetch()}
            variant="ghost"
            size="small"
            disabled={checkUpdate.isFetching}
          />
        </View>
      </View>

      {showRestartModal && (
        <RestartConfirmModal onClose={() => setShowRestartModal(false)} />
      )}
    </>
  );
}
