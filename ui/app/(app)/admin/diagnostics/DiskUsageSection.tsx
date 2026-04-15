import { Spinner } from "@/src/components/shared/Spinner";
import { HardDrive, Database, Paperclip } from "lucide-react";
import { Link } from "react-router-dom";
import { useThemeTokens } from "@/src/theme/tokens";
import { useDiskUsage, type WorkspaceDiskEntry } from "@/src/api/hooks/useDiagnostics";
import { formatBytes } from "@/src/utils/format";

function UsageBar({ percent }: { percent: number }) {
  const t = useThemeTokens();
  const color = percent >= 90 ? t.danger : percent >= 75 ? t.warning : t.accent;
  return (
    <div style={{ height: 8, borderRadius: 4, background: t.surfaceOverlay, overflow: "hidden" }}>
      <div style={{
        height: "100%", borderRadius: 4, background: color,
        width: `${Math.min(percent, 100)}%`, transition: "width 0.3s",
      }} />
    </div>
  );
}

function WorkspaceCard({ ws }: { ws: WorkspaceDiskEntry }) {
  const t = useThemeTokens();
  return (
    <div style={{
      padding: "12px 16px", background: t.inputBg, borderRadius: 8,
      border: `1px solid ${t.surfaceRaised}`,
    }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <Database size={14} color={t.textMuted} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>
          {ws.name}
        </span>
        <span style={{
          padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
          background: ws.type === "shared" ? t.accentSubtle : "rgba(100,100,100,0.15)",
          color: ws.type === "shared" ? t.accent : t.textDim,
        }}>
          {ws.type}
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 16, fontSize: 12, color: t.textDim }}>
        <span>Size: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{formatBytes(ws.total_bytes)}</span></span>
        <span>Files: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{ws.file_count.toLocaleString()}</span></span>
      </div>

      {ws.subdirs && Object.keys(ws.subdirs).length > 0 && (
        <div style={{ marginTop: 8, display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 12, fontSize: 11, color: t.textDim }}>
          {Object.entries(ws.subdirs).map(([name, bytes]) => (
            <span key={name}>
              {name}: <span style={{ fontFamily: "monospace", color: t.textMuted }}>{formatBytes(bytes)}</span>
            </span>
          ))}
        </div>
      )}

      <div style={{ marginTop: 6, fontSize: 10, color: t.textDim, fontFamily: "monospace", wordBreak: "break-all" }}>
        {ws.path}
      </div>
    </div>
  );
}

export function DiskUsageSection() {
  const t = useThemeTokens();
  const { data, isLoading } = useDiskUsage();

  if (isLoading) {
    return (
      <div style={{ padding: 24, display: "flex", flexDirection: "row", justifyContent: "center" }}>
        <Spinner color={t.accent} />
      </div>
    );
  }

  if (!data) return null;

  const { filesystem: fs, workspaces } = data;
  const statusColor = fs.usage_percent >= 90 ? t.danger : fs.usage_percent >= 75 ? t.warning : t.success;

  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
        Disk Usage
      </div>

      {/* Filesystem overview */}
      <div style={{
        padding: "14px 16px", background: t.inputBg, borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`, marginBottom: 10,
      }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <HardDrive size={14} color={t.textMuted} />
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>Filesystem</span>
          <span style={{ fontSize: 11, color: statusColor, fontWeight: 600 }}>
            {fs.usage_percent}% used
          </span>
        </div>

        <UsageBar percent={fs.usage_percent} />

        <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 16, fontSize: 12, color: t.textDim, marginTop: 10 }}>
          <span>Total: <span style={{ color: t.text, fontFamily: "monospace" }}>{formatBytes(fs.total_bytes)}</span></span>
          <span>Used: <span style={{ color: t.text, fontFamily: "monospace" }}>{formatBytes(fs.used_bytes)}</span></span>
          <span>Free: <span style={{ color: t.text, fontFamily: "monospace" }}>{formatBytes(fs.free_bytes)}</span></span>
          <span>Workspaces: <span style={{ color: t.text, fontFamily: "monospace" }}>{formatBytes(data.workspace_total_bytes)}</span></span>
        </div>

        <div style={{ marginTop: 6, fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
          {data.workspace_base_dir}
        </div>
      </div>

      {/* Attachment storage */}
      {data.attachments && (
        <div style={{
          padding: "14px 16px", background: t.inputBg, borderRadius: 8,
          border: `1px solid ${t.surfaceRaised}`, marginBottom: 10,
        }}>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
            <Paperclip size={14} color={t.textMuted} />
            <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>Attachments</span>
            <Link to="/admin/attachments">
              <span style={{ fontSize: 11, color: t.accent, cursor: "pointer" }}>Manage →</span>
            </Link>
          </div>
          <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 16, fontSize: 12, color: t.textDim }}>
            <span>Total: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{data.attachments.total_count.toLocaleString()}</span></span>
            <span>With data: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{data.attachments.with_file_data_count.toLocaleString()}</span></span>
            <span>Size: <span style={{ color: t.text, fontWeight: 600, fontFamily: "monospace" }}>{formatBytes(data.attachments.total_size_bytes)}</span></span>
          </div>
        </div>
      )}

      {/* Per-workspace cards */}
      {workspaces.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {workspaces.map((ws) => (
            <WorkspaceCard key={ws.id} ws={ws} />
          ))}
        </div>
      ) : (
        <div style={{ padding: 16, fontSize: 12, color: t.textDim, textAlign: "center" }}>
          No workspaces found.
        </div>
      )}
    </div>
  );
}
