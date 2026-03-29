import { useThemeTokens } from "@/src/theme/tokens";
import { useTool } from "@/src/api/hooks/useTools";
import { X } from "lucide-react";

export function ToolSchemaModal({
  toolName,
  onClose,
}: {
  toolName: string;
  onClose: () => void;
}) {
  const t = useThemeTokens();
  const { data: tool, isLoading, error } = useTool(toolName);

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
          background: t.surface,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 10,
          width: "90%",
          maxWidth: 640,
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 16px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <span
            style={{
              fontFamily: "monospace",
              fontSize: 14,
              fontWeight: 600,
              color: t.text,
            }}
          >
            {toolName}
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 4,
              color: t.textDim,
            }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: 16, overflow: "auto", flex: 1 }}>
          {isLoading && (
            <span style={{ fontSize: 12, color: t.textDim }}>Loading...</span>
          )}
          {error && (
            <span style={{ fontSize: 12, color: "#ef4444" }}>
              Failed to load tool schema
            </span>
          )}
          {tool && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {/* Description */}
              {tool.description && (
                <p
                  style={{
                    fontSize: 12,
                    color: t.textMuted,
                    margin: 0,
                    lineHeight: 1.5,
                  }}
                >
                  {tool.description}
                </p>
              )}

              {/* Source info */}
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  fontSize: 10,
                  color: t.textDim,
                  flexWrap: "wrap",
                }}
              >
                {tool.source_integration && (
                  <span>integration: {tool.source_integration}</span>
                )}
                {tool.source_file && <span>file: {tool.source_file}</span>}
                {tool.server_name && <span>mcp: {tool.server_name}</span>}
              </div>

              {/* Schema JSON */}
              <div>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    color: t.textDim,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    marginBottom: 4,
                  }}
                >
                  OpenAI Function Schema
                </div>
                <pre
                  style={{
                    background: t.codeBg,
                    border: `1px solid ${t.codeBorder}`,
                    borderRadius: 6,
                    padding: 12,
                    fontSize: 11,
                    fontFamily: "monospace",
                    color: t.codeText,
                    overflow: "auto",
                    margin: 0,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    maxHeight: 400,
                  }}
                >
                  {JSON.stringify(tool.schema_ ?? {}, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
