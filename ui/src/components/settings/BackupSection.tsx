import { useState, useEffect } from "react";
import { Play, Save, Archive, FolderOpen } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { OperationsPanel } from "@/app/(app)/admin/diagnostics/OperationsPanel";
import {
  useBackupConfig,
  useUpdateBackupConfig,
  useTriggerBackup,
  useBackupHistory,
  type BackupConfig,
} from "@/src/api/hooks/useBackup";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / 1024 ** i).toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

// ---------------------------------------------------------------------------
// Backup Config Form
// ---------------------------------------------------------------------------

function BackupConfigForm() {
  const t = useThemeTokens();
  const { data, isLoading } = useBackupConfig();
  const updateMut = useUpdateBackupConfig();
  const [form, setForm] = useState<Partial<BackupConfig>>({});
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data) {
      setForm({
        rclone_remote: data.rclone_remote,
        local_keep: data.local_keep,
        aws_region: data.aws_region,
        backup_dir: data.backup_dir,
      });
      setDirty(false);
    }
  }, [data]);

  const handleChange = (field: keyof BackupConfig, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    setDirty(true);
  };

  const handleSave = async () => {
    const payload: Partial<BackupConfig> = { ...form };
    if (form.local_keep !== undefined) {
      payload.local_keep = Number(form.local_keep);
    }
    await updateMut.mutateAsync(payload);
    setDirty(false);
  };

  if (isLoading) {
    return (
      <div style={{ padding: 24, textAlign: "center" }}>
        <div className="chat-spinner" />
      </div>
    );
  }

  const fields: { key: keyof BackupConfig; label: string; placeholder: string }[] = [
    { key: "rclone_remote", label: "Rclone Remote", placeholder: "e.g. s3:my-bucket/backups" },
    { key: "backup_dir", label: "Local Backup Dir", placeholder: "./backups" },
    { key: "local_keep", label: "Local Keep (days)", placeholder: "7" },
    { key: "aws_region", label: "AWS Region", placeholder: "us-east-1" },
  ];

  return (
    <div style={{
      padding: 16, background: t.inputBg, borderRadius: 8,
      border: `1px solid ${t.surfaceRaised}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 14,
        fontSize: 12, fontWeight: 600, color: t.textMuted,
        textTransform: "uppercase", letterSpacing: 1,
      }}>
        <FolderOpen size={14} />
        Configuration
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {fields.map(({ key, label, placeholder }) => (
          <div key={key}>
            <label style={{ fontSize: 11, color: t.textDim, display: "block", marginBottom: 4 }}>
              {label}
            </label>
            <input
              value={String(form[key] ?? "")}
              onChange={(e) => handleChange(key, e.target.value)}
              placeholder={placeholder}
              style={{
                width: "100%", padding: "8px 10px", fontSize: 13,
                background: t.surface, color: t.text,
                border: `1px solid ${t.surfaceOverlay}`, borderRadius: 6,
                fontFamily: "monospace", outline: "none",
                boxSizing: "border-box",
              }}
            />
          </div>
        ))}
      </div>

      {(dirty || updateMut.isError) && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12 }}>
          <button
            onClick={handleSave}
            disabled={updateMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: t.accent, color: "#fff", cursor: "pointer",
              opacity: updateMut.isPending ? 0.6 : 1,
            }}
          >
            <Save size={13} />
            {updateMut.isPending ? "Saving..." : "Save Config"}
          </button>
          {updateMut.isError && (
            <span style={{ fontSize: 12, color: t.danger }}>
              Failed to save: {(updateMut.error as Error).message}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Backup Actions
// ---------------------------------------------------------------------------

function BackupActions() {
  const t = useThemeTokens();
  const triggerMut = useTriggerBackup();

  return (
    <div style={{
      padding: 16, background: t.inputBg, borderRadius: 8,
      border: `1px solid ${t.surfaceRaised}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 14,
        fontSize: 12, fontWeight: 600, color: t.textMuted,
        textTransform: "uppercase", letterSpacing: 1,
      }}>
        <Play size={14} />
        Run Backup
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button
          onClick={() => triggerMut.mutate()}
          disabled={triggerMut.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "8px 18px", fontSize: 13, fontWeight: 600,
            border: "none", borderRadius: 6,
            background: t.accent, color: "#fff", cursor: "pointer",
            opacity: triggerMut.isPending ? 0.6 : 1,
          }}
        >
          <Play size={14} />
          {triggerMut.isPending ? "Starting..." : "Run Backup Now"}
        </button>

        {triggerMut.isSuccess && (
          <span style={{ fontSize: 12, color: t.success }}>
            Backup started (op: {triggerMut.data.operation_id})
          </span>
        )}
        {triggerMut.isError && (
          <span style={{ fontSize: 12, color: t.danger }}>
            Failed: {(triggerMut.error as Error).message}
          </span>
        )}
      </div>

      <div style={{ marginTop: 14 }}>
        <OperationsPanel />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Backup History
// ---------------------------------------------------------------------------

function BackupHistory() {
  const t = useThemeTokens();
  const { data, isLoading } = useBackupHistory();

  return (
    <div style={{
      padding: 16, background: t.inputBg, borderRadius: 8,
      border: `1px solid ${t.surfaceRaised}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 14,
        fontSize: 12, fontWeight: 600, color: t.textMuted,
        textTransform: "uppercase", letterSpacing: 1,
      }}>
        <Archive size={14} />
        History
      </div>

      {isLoading && (
        <div style={{ padding: 16, textAlign: "center" }}>
          <div className="chat-spinner" />
        </div>
      )}

      {data && data.files.length === 0 && (
        <div style={{ padding: 16, fontSize: 13, color: t.textDim, textAlign: "center" }}>
          No backup archives found in {data.backup_dir}
        </div>
      )}

      {data && data.files.length > 0 && (
        <>
          <div style={{ fontSize: 11, color: t.textDim, marginBottom: 10 }}>
            Directory: <span style={{ fontFamily: "monospace" }}>{data.backup_dir}</span>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${t.surfaceOverlay}` }}>
                <th style={{ textAlign: "left", padding: "6px 8px", fontSize: 11, color: t.textDim, fontWeight: 600 }}>
                  File
                </th>
                <th style={{ textAlign: "right", padding: "6px 8px", fontSize: 11, color: t.textDim, fontWeight: 600 }}>
                  Size
                </th>
                <th style={{ textAlign: "right", padding: "6px 8px", fontSize: 11, color: t.textDim, fontWeight: 600 }}>
                  Date
                </th>
              </tr>
            </thead>
            <tbody>
              {data.files.map((f) => (
                <tr key={f.name} style={{ borderBottom: `1px solid ${t.surfaceOverlay}` }}>
                  <td style={{ padding: "8px", color: t.text, fontFamily: "monospace", fontSize: 12 }}>
                    {f.name}
                  </td>
                  <td style={{ padding: "8px", textAlign: "right", color: t.textMuted, fontSize: 12 }}>
                    {formatBytes(f.size_bytes)}
                  </td>
                  <td style={{ padding: "8px", textAlign: "right", color: t.textDim, fontSize: 12 }}>
                    {formatDate(f.modified_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exported section — dropped into settings page
// ---------------------------------------------------------------------------

export function BackupSection() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <BackupConfigForm />
      <BackupActions />
      <BackupHistory />
    </div>
  );
}
