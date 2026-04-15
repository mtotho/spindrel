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

/**
 * Compact single-row server status strip. Shows status dot, version,
 * pause/restart controls, and update check — all inline.
 */
export function ServerStatusStrip() {
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
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 10,
          padding: "6px 16px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          flexWrap: "wrap",
        }}
      >
        {/* Status dot + badge */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          <div
            style={{
              width: 7,
              height: 7,
              borderRadius: "50%",
              backgroundColor: paused ? t.warning : t.success,
              flexShrink: 0,
            }}
          />
          <StatusBadge
            label={paused ? "Paused" : "Running"}
            variant={paused ? "warning" : "success"}
          />
        </div>

        {/* Version */}
        <span style={{ color: t.textDim, fontSize: 11, fontFamily: "monospace" }}>
          v{version ?? "..."}
        </span>

        {/* Update result (inline) */}
        {checkUpdate.data && !checkUpdate.isFetching && (
          checkUpdate.data.update_available ? (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
              <StatusBadge label={`v${checkUpdate.data.latest} available`} variant="info" />
              {checkUpdate.data.latest_url && (
                <a
                  href={checkUpdate.data.latest_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ display: "flex", flexDirection: "row", alignItems: "center" }}
                >
                  <ExternalLink size={10} color={t.accent} />
                </a>
              )}
            </div>
          ) : checkUpdate.data.error ? (
            <span style={{ color: t.textDim, fontSize: 10 }}>Check failed</span>
          ) : (
            <span style={{ color: t.success, fontSize: 10 }}>Up to date</span>
          )
        )}
        {checkUpdate.isFetching && <div className="chat-spinner" />}

        <div style={{ flex: 1 }} />

        {/* Actions — right-aligned */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
          <button
            type="button"
            onClick={() => checkUpdate.refetch()}
            disabled={checkUpdate.isFetching}
            style={{
              background: "none",
              border: "none",
              cursor: checkUpdate.isFetching ? "not-allowed" : "pointer",
              color: t.textDim,
              fontSize: 10,
              padding: "2px 6px",
              opacity: checkUpdate.isFetching ? 0.5 : 1,
            }}
          >
            Update
          </button>
          <ActionButton
            label={togglePause.isPending ? "..." : paused ? "Resume" : "Pause"}
            onPress={() => togglePause.mutate(!paused)}
            variant={paused ? "primary" : "secondary"}
            size="small"
            disabled={togglePause.isPending}
          />
          <ActionButton
            label="Restart"
            onPress={() => setShowRestartModal(true)}
            variant="danger"
            size="small"
            icon={<RefreshCw size={11} />}
          />
        </div>
      </div>

      {showRestartModal && (
        <RestartConfirmModal onClose={() => setShowRestartModal(false)} />
      )}
    </>
  );
}

/** @deprecated Use ServerStatusStrip instead */
export function ServerStatusBar() {
  return <ServerStatusStrip />;
}
