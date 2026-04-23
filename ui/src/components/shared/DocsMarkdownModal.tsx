import { useEffect } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { useDocsPage } from "@/src/api/hooks/useIntegrations";
import { Spinner } from "@/src/components/shared/Spinner";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
import { useThemeTokens } from "@/src/theme/tokens";

interface DocsMarkdownModalProps {
  path: string;
  title: string;
  onClose: () => void;
  errorMessage?: string;
  width?: number;
}

export function DocsMarkdownModal({
  path,
  title,
  onClose,
  errorMessage = "Failed to load documentation.",
  width = 720,
}: DocsMarkdownModalProps) {
  const t = useThemeTokens();
  const { data, isLoading, isError } = useDocsPage(path);

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
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 10020,
        }}
      />
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width,
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
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "16px 20px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>
            {title}
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
              {errorMessage}
            </div>
          )}
          {data?.content && <MarkdownViewer content={data.content} />}
        </div>
      </div>
    </>,
    document.body,
  );
}
