import { useState } from "react";
import { X } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { useCreatePromptTemplate } from "../../api/hooks/usePromptTemplates";

interface Props {
  content: string;
  onClose: () => void;
  onSaved?: (id: string) => void;
}

export function SaveAsTemplateModal({ content, onClose, onSaved }: Props) {
  const t = useThemeTokens();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const createMutation = useCreatePromptTemplate();

  const canSave = name.trim().length > 0 && !createMutation.isPending;

  const handleSave = async () => {
    if (!canSave) return;
    try {
      const result = await createMutation.mutateAsync({
        name: name.trim(),
        description: description.trim() || undefined,
        content,
        category: "workspace_schema",
      });
      onSaved?.(result.id);
      onClose();
    } catch {
      // mutation error is handled by react-query
    }
  };

  if (typeof document === "undefined") return null;

  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const ReactDOM = require("react-dom");
  return ReactDOM.createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
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
          width: 400,
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
        <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Save as New Template</span>
          <button
            onClick={onClose}
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              background: "transparent",
              border: "none",
              cursor: "pointer",
              padding: 4,
            }}
          >
            <X size={16} color={t.textDim} />
          </button>
        </div>

        {/* Name */}
        <div style={{ marginBottom: 12 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: t.textDim, marginBottom: 4, display: "block" }}>Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. My Custom Schema"
            autoFocus
            style={{
              width: "100%",
              background: t.inputBg,
              border: `1px solid ${t.inputBorder}`,
              borderRadius: 6,
              padding: 8,
              fontSize: 13,
              color: t.inputText,
              outline: "none",
            }}
          />
        </div>

        {/* Description */}
        <div style={{ marginBottom: 16 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: t.textDim, marginBottom: 4, display: "block" }}>Description (optional)</span>
          <input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brief description of this schema"
            style={{
              width: "100%",
              background: t.inputBg,
              border: `1px solid ${t.inputBorder}`,
              borderRadius: 6,
              padding: 8,
              fontSize: 13,
              color: t.inputText,
              outline: "none",
            }}
          />
        </div>

        {/* Actions */}
        <div style={{ display: "flex", flexDirection: "row", justifyContent: "flex-end", gap: 8 }}>
          <button
            onClick={onClose}
            style={{
              paddingLeft: 12,
              paddingRight: 12,
              paddingTop: 6,
              paddingBottom: 6,
              borderRadius: 6,
              border: `1px solid ${t.surfaceBorder}`,
              background: "transparent",
              cursor: "pointer",
              fontSize: 12,
              color: t.textDim,
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!canSave}
            style={{
              paddingLeft: 12,
              paddingRight: 12,
              paddingTop: 6,
              paddingBottom: 6,
              borderRadius: 6,
              background: canSave ? t.accent : t.surfaceOverlay,
              border: "none",
              opacity: canSave ? 1 : 0.5,
              cursor: canSave ? "pointer" : "default",
              fontSize: 12,
              fontWeight: 600,
              color: "#fff",
            }}
          >
            {createMutation.isPending ? (
              <div className="chat-spinner" />
            ) : (
              "Save Template"
            )}
          </button>
        </div>

        {createMutation.isError && (
          <span style={{ color: t.danger, fontSize: 11, marginTop: 8, display: "block" }}>
            Failed to save template. Please try again.
          </span>
        )}
      </div>
    </>,
    document.body
  );
}
