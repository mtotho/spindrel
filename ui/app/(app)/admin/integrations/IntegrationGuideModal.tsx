/**
 * Modal displaying integration documentation from docs/integrations/index.md.
 * Uses portal pattern consistent with CarapaceHelpModal.
 */
import { useEffect } from "react";
import { Pressable, ActivityIndicator } from "react-native";
import { X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
import { useDocsPage } from "@/src/api/hooks/useIntegrations";

interface Props {
  onClose: () => void;
}

export function IntegrationGuideModal({ onClose }: Props) {
  const t = useThemeTokens();
  const { data, isLoading, isError } = useDocsPage("integrations/index");

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

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
          width: 680,
          maxWidth: "92vw",
          maxHeight: "85vh",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "16px 20px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>
            Integration Guide
          </span>
          <Pressable onPress={onClose} hitSlop={8}>
            <X size={16} color={t.textDim} />
          </Pressable>
        </div>

        {/* Scrollable body */}
        <div style={{ overflow: "auto", flex: 1 }}>
          {isLoading && (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                padding: 40,
              }}
            >
              <ActivityIndicator color={t.accent} />
            </div>
          )}
          {isError && (
            <div
              style={{
                padding: 20,
                fontSize: 13,
                color: t.textDim,
                textAlign: "center",
              }}
            >
              Failed to load integration documentation.
            </div>
          )}
          {data?.content && <MarkdownViewer content={data.content} />}
        </div>
      </div>
    </>,
    document.body,
  );
}
