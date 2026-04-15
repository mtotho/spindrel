import { AlertTriangle, Wifi, WifiOff } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useDeviceStatus,
  type DeviceStatusInfo,
} from "@/src/api/hooks/useIntegrations";

const STATUS_COLORS: Record<string, string> = {
  connected: "#22c55e",
  disconnected: "#6b7280",
  connecting: "#eab308",
  error: "#ef4444",
};

function StatusDot({ status }: { status: string }) {
  const color = STATUS_COLORS[status] || "#6b7280";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        flexShrink: 0,
      }}
    />
  );
}

function formatTimeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function DeviceRow({ device }: { device: DeviceStatusInfo }) {
  const t = useThemeTokens();
  const isUp = device.status === "connected";
  return (
    <div
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 10,
        padding: "8px 0",
        borderBottom: `1px solid ${t.surfaceRaised}`,
        fontSize: 12,
      }}
    >
      <StatusDot status={device.status} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, color: t.text }}>{device.label}</div>
        <div
          style={{
            fontSize: 10,
            color: t.textDim,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {device.protocol} &middot; {device.uri}
          {device.detail && (
            <span style={{ color: "#ef4444", marginLeft: 6 }}>
              {device.detail}
            </span>
          )}
        </div>
      </div>
      <div
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 4,
          fontSize: 11,
          color: STATUS_COLORS[device.status] || t.textMuted,
          fontWeight: 600,
          flexShrink: 0,
        }}
      >
        {isUp ? <Wifi size={12} /> : <WifiOff size={12} />}
        {device.status}
      </div>
      {device.last_activity && (
        <span
          style={{
            fontSize: 10,
            color: t.textDim,
            fontFamily: "monospace",
            flexShrink: 0,
            minWidth: 60,
            textAlign: "right",
          }}
        >
          {formatTimeAgo(device.last_activity)}
        </span>
      )}
    </div>
  );
}

export function DeviceStatusSection({
  integrationId,
}: {
  integrationId: string;
}) {
  const t = useThemeTokens();
  const { data } = useDeviceStatus(integrationId);

  if (!data || data.devices.length === 0) return null;

  const connectedCount = data.devices.filter(
    (d) => d.status === "connected"
  ).length;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: 14,
        background: t.inputBg,
        borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
      }}
    >
      <div
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: t.textDim,
            textTransform: "uppercase",
            letterSpacing: 0.6,
          }}
        >
          Connected Devices
        </span>
        <span
          style={{
            fontSize: 10,
            color: t.textMuted,
            fontFamily: "monospace",
          }}
        >
          {connectedCount}/{data.devices.length} online
        </span>
      </div>

      {data.stale && (
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 6,
            padding: "4px 8px",
            borderRadius: 5,
            background: "rgba(234,179,8,0.08)",
            border: "1px solid rgba(234,179,8,0.2)",
            fontSize: 11,
            color: "#ca8a04",
          }}
        >
          <AlertTriangle size={12} />
          Status data is stale — process may not be running
        </div>
      )}

      <div
        style={{
          borderRadius: 6,
          background: t.surface,
          border: `1px solid ${t.surfaceBorder}`,
          padding: "0 10px",
        }}
      >
        {data.devices.map((device) => (
          <DeviceRow key={device.device_id} device={device} />
        ))}
      </div>
    </div>
  );
}
