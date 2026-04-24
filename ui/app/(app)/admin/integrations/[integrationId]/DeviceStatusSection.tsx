import { AlertTriangle, Wifi, WifiOff } from "lucide-react";
import { useDeviceStatus, type DeviceStatusInfo } from "@/src/api/hooks/useIntegrations";
import { InfoBanner, SettingsControlRow, SettingsGroupLabel, StatusBadge } from "@/src/components/shared/SettingsControls";

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

function variantFor(status: DeviceStatusInfo["status"]): "success" | "warning" | "danger" | "neutral" {
  if (status === "connected") return "success";
  if (status === "connecting") return "warning";
  if (status === "error") return "danger";
  return "neutral";
}

function DeviceRow({ device }: { device: DeviceStatusInfo }) {
  const up = device.status === "connected";
  return (
    <SettingsControlRow
      leading={up ? <Wifi size={14} /> : <WifiOff size={14} />}
      title={device.label}
      description={
        <span className="space-y-0.5">
          <span className="block truncate">{device.protocol} · {device.uri}</span>
          {device.detail && <span className="block text-danger">{device.detail}</span>}
        </span>
      }
      meta={
        <span className="inline-flex items-center gap-1.5">
          <StatusBadge label={device.status} variant={variantFor(device.status)} />
          {device.last_activity && <span>{formatTimeAgo(device.last_activity)}</span>}
        </span>
      }
    />
  );
}

export function DeviceStatusSection({ integrationId }: { integrationId: string }) {
  const { data } = useDeviceStatus(integrationId);
  if (!data || data.devices.length === 0) return null;

  const connectedCount = data.devices.filter((device) => device.status === "connected").length;

  return (
    <div className="flex flex-col gap-3">
      <SettingsGroupLabel label="Connected Devices" count={data.devices.length} />
      <div className="text-[11px] text-text-dim">{connectedCount}/{data.devices.length} online</div>
      {data.stale && (
        <InfoBanner variant="warning" icon={<AlertTriangle size={14} />}>
          Status data is stale. The integration process may not be running.
        </InfoBanner>
      )}
      <div className="flex flex-col gap-1.5">
        {data.devices.map((device) => <DeviceRow key={device.device_id} device={device} />)}
      </div>
    </div>
  );
}
