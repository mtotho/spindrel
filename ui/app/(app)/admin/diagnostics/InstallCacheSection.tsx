import { useState } from "react";
import { Archive, Package, Trash2 } from "lucide-react";
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import {
  useInstallCacheStats,
  useClearInstallCache,
} from "@/src/api/hooks/useInstallCache";
import { formatBytes } from "@/src/utils/format";

export function InstallCacheSection() {
  const t = useThemeTokens();
  const { data, isLoading } = useInstallCacheStats();
  const clearMut = useClearInstallCache();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [lastFreed, setLastFreed] = useState<number | null>(null);
  const [lastErrors, setLastErrors] = useState<string[]>([]);

  const handleClear = async () => {
    const ok = await confirm(
      "Wipe the persistent install cache? The next package install will re-download from the network (slower). Apt-installed binaries will reinstall on next boot.",
      {
        title: "Clear install cache",
        confirmLabel: "Clear",
        variant: "danger",
      },
    );
    if (!ok) return;
    try {
      const res = await clearMut.mutateAsync("all");
      setLastFreed(res.freed_bytes);
      setLastErrors(res.errors);
    } catch {
      /* mutation error surfaced via clearMut.error */
    }
  };

  return (
    <div>
      <ConfirmDialogSlot />
      <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
        Install Cache
      </div>

      <div style={{
        padding: "14px 16px", background: t.inputBg, borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
      }}>
        <div style={{ fontSize: 11, color: t.textDim, marginBottom: 12, lineHeight: 1.5 }}>
          Two Docker volumes persist package caches and installed binaries across <code style={{ fontFamily: "monospace", color: t.textMuted }}>spindrel pull</code> rebuilds.
          Home (<code style={{ fontFamily: "monospace" }}>~/.local</code>, <code style={{ fontFamily: "monospace" }}>~/.cache</code>) survives intact; apt binaries reinstall from the archive cache on boot (fast, no network).
        </div>

        {isLoading && (
          <div style={{ padding: 8, display: "flex", justifyContent: "center" }}>
            <Spinner color={t.accent} />
          </div>
        )}

        {data && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
            <CacheStatCard
              icon={<Package size={14} color={t.textMuted} />}
              label="Home"
              path={data.home_path}
              bytes={data.home_bytes}
              exists={data.home_exists}
            />
            <CacheStatCard
              icon={<Archive size={14} color={t.textMuted} />}
              label="Apt archives"
              path={data.apt_path}
              bytes={data.apt_bytes}
              exists={data.apt_exists}
            />
          </div>
        )}

        {lastFreed !== null && (
          <div style={{
            padding: "8px 12px", marginBottom: 10, fontSize: 12,
            background: lastErrors.length ? t.dangerSubtle : t.successSubtle,
            border: `1px solid ${lastErrors.length ? t.dangerBorder : `${t.success}33`}`,
            borderRadius: 6,
            color: lastErrors.length ? t.danger : t.success,
          }}>
            Cleared — freed <strong style={{ fontFamily: "monospace" }}>{formatBytes(lastFreed)}</strong>.
            {lastErrors.length > 0 && (
              <div style={{ marginTop: 4, fontSize: 11, fontFamily: "monospace" }}>
                {lastErrors.slice(0, 3).map((e, i) => <div key={i}>{e}</div>)}
                {lastErrors.length > 3 && <div>…and {lastErrors.length - 3} more</div>}
              </div>
            )}
          </div>
        )}

        <button
          onClick={handleClear}
          disabled={clearMut.isPending || !data}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
            padding: "6px 14px", fontSize: 12, fontWeight: 600,
            border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
            background: "transparent", color: t.danger,
            cursor: clearMut.isPending ? "default" : "pointer",
            opacity: clearMut.isPending || !data ? 0.6 : 1,
          }}
        >
          <Trash2 size={14} />
          {clearMut.isPending ? "Clearing…" : "Clear install cache"}
        </button>
      </div>
    </div>
  );
}

function CacheStatCard({
  icon, label, path, bytes, exists,
}: {
  icon: React.ReactNode;
  label: string;
  path: string;
  bytes: number;
  exists: boolean;
}) {
  const t = useThemeTokens();
  return (
    <div style={{
      padding: "10px 12px", background: t.surface, borderRadius: 6,
      border: `1px solid ${exists ? t.surfaceOverlay : t.dangerBorder}`,
    }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 6 }}>
        {icon}
        <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{label}</span>
        {!exists && <span style={{ fontSize: 10, color: t.danger }}>(missing)</span>}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, fontFamily: "monospace", color: t.text }}>
        {formatBytes(bytes)}
      </div>
      <div style={{ marginTop: 4, fontSize: 10, color: t.textDim, fontFamily: "monospace", wordBreak: "break-all" }}>
        {path}
      </div>
    </div>
  );
}
