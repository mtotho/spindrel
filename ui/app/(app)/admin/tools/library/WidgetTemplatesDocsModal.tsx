import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { Spinner } from "@/src/components/shared/Spinner";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
import { useDocsPage } from "@/src/api/hooks/useIntegrations";
import { useThemeTokens } from "@/src/theme/tokens";

interface Props {
  onClose: () => void;
}

export function WidgetTemplatesDocsModal({ onClose }: Props) {
  const t = useThemeTokens();
  const { data, isLoading, isError } = useDocsPage("widget-templates");

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <>
      <div
        onClick={onClose}
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 10020 }}
      />
      <div
        style={{
          position: "fixed",
          top: "50%", left: "50%", transform: "translate(-50%, -50%)",
          width: 720, maxWidth: "92vw", maxHeight: "85vh",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          display: "flex", flexDirection: "column", overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex", flexDirection: "row",
            justifyContent: "space-between", alignItems: "center",
            padding: "16px 20px", borderBottom: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>
            Widget Templates
          </span>
          <button type="button" onClick={onClose}>
            <X size={16} color={t.textDim} />
          </button>
        </div>
        <div style={{ overflow: "auto", flex: 1 }}>
          {isLoading && (
            <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
              <Spinner color={t.accent} />
            </div>
          )}
          {isError && (
            <div style={{ padding: 20, fontSize: 13, color: t.textDim, textAlign: "center" }}>
              Failed to load widget-templates documentation.
            </div>
          )}
          {data?.content && <MarkdownViewer content={data.content} />}
        </div>
      </div>
    </>,
    document.body,
  );
}
