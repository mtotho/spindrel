import { useState } from "react";
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
      <div
        style={{
          backgroundColor: t.surfaceRaised,
          borderRadius: 10,
          border: `1px solid ${t.surfaceBorder}`,
          padding: 14,
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {/* Row 1: Status + controls */}
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          {/* Status indicator */}
          <div
            style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}
          >
            <div
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
          </div>

          <div style={{ flex: 1 }} />

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
        </div>

        {/* Row 2: Version + update check */}
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <span style={{ color: t.textDim, fontSize: 12, fontFamily: "monospace" }}>
            Spindrel v{version ?? "..."}
            {checkUpdate.data?.git_hash
              ? ` (${checkUpdate.data.git_hash})`
              : ""}
          </span>

          <div style={{ flex: 1 }} />

          {/* Update check result */}
          {checkUpdate.data && !checkUpdate.isFetching && (
            checkUpdate.data.update_available ? (
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
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
              </div>
            ) : checkUpdate.data.error ? (
              <span style={{ color: t.textDim, fontSize: 11 }}>
                Check failed
              </span>
            ) : (
              <span style={{ color: t.success, fontSize: 11 }}>
                Up to date
              </span>
            )
          )}

          {checkUpdate.isFetching && (
            <div className="chat-spinner" />
          )}

          <ActionButton
            label="Check for Update"
            onPress={() => checkUpdate.refetch()}
            variant="ghost"
            size="small"
            disabled={checkUpdate.isFetching}
          />
        </div>
      </div>

      {showRestartModal && (
        <RestartConfirmModal onClose={() => setShowRestartModal(false)} />
      )}
    </>
  );
}
