import { useState, useRef } from "react";
import { Upload, X, FolderOpen } from "lucide-react";
import { useUploadWorkspaceFile } from "../../api/hooks/useWorkspaces";
import { useThemeTokens } from "../../theme/tokens";

interface UploadDialogProps {
  workspaceId: string;
  currentDir: string;
  onClose: () => void;
}

export function UploadDialog({ workspaceId, currentDir, onClose }: UploadDialogProps) {
  const t = useThemeTokens();
  const [files, setFiles] = useState<File[]>([]);
  const [targetDir, setTargetDir] = useState(currentDir);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadMutation = useUploadWorkspaceFile(workspaceId);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles(Array.from(e.target.files));
    }
  };

  const handleUpload = async () => {
    if (files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of files) {
        await uploadMutation.mutateAsync({ file, targetDir });
      }
      onClose();
    } catch (e: any) {
      setError(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 8,
          padding: 24,
          width: 420,
          maxWidth: "90vw",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <span style={{ fontSize: 16, fontWeight: 600, color: t.text }}>Upload Files</span>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: t.textDim, padding: 4 }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Target directory */}
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: t.textMuted, display: "block", marginBottom: 4 }}>
            Target directory
          </label>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <FolderOpen size={14} color={t.textDim} />
            <input
              value={targetDir}
              onChange={(e) => setTargetDir(e.target.value)}
              style={{
                flex: 1,
                background: t.inputBg,
                border: `1px solid ${t.inputBorder}`,
                borderRadius: 4,
                padding: "6px 10px",
                color: t.inputText,
                fontSize: 13,
                outline: "none",
                fontFamily: "monospace",
              }}
            />
          </div>
        </div>

        {/* File picker */}
        <div
          onClick={() => inputRef.current?.click()}
          style={{
            border: `2px dashed ${t.surfaceBorder}`,
            borderRadius: 8,
            padding: 24,
            textAlign: "center",
            cursor: "pointer",
            marginBottom: 16,
          }}
        >
          <Upload size={24} color={t.textDim} style={{ margin: "0 auto 8px" }} />
          <div style={{ fontSize: 13, color: t.textMuted }}>
            {files.length > 0 ? `${files.length} file(s) selected` : "Click to select files"}
          </div>
          {files.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 11, color: t.textDim }}>
              {files.map((f) => f.name).join(", ")}
            </div>
          )}
          <input
            ref={inputRef}
            type="file"
            multiple
            onChange={handleFileSelect}
            style={{ display: "none" }}
          />
        </div>

        {error && (
          <div style={{ color: t.danger, fontSize: 12, marginBottom: 12 }}>{error}</div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6,
              padding: "6px 16px",
              color: t.textMuted,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleUpload}
            disabled={files.length === 0 || uploading}
            style={{
              background: files.length === 0 || uploading ? t.surfaceBorder : t.accent,
              border: "none",
              borderRadius: 6,
              padding: "6px 16px",
              color: "#fff",
              fontSize: 13,
              fontWeight: 600,
              cursor: files.length === 0 || uploading ? "not-allowed" : "pointer",
            }}
          >
            {uploading ? "Uploading..." : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
