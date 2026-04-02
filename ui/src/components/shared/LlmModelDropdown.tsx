import { useState, useRef, useCallback } from "react";
import {
  useModelGroups,
  useEmbeddingModelGroups,
  useDownloadEmbeddingModel,
} from "../../api/hooks/useModels";
import { useThemeTokens } from "../../theme/tokens";
import type { LlmModel } from "../../types/api";

interface Props {
  value: string;
  onChange: (modelId: string, providerId?: string | null) => void;
  placeholder?: string;
  label?: string;
  allowClear?: boolean;
  /** Where to anchor the dropdown relative to the trigger. Default "bottom". */
  anchor?: "bottom" | "top";
  /** "llm" (default) fetches /models; "embedding" fetches /embedding-models (includes local fastembed). */
  variant?: "llm" | "embedding";
  /** When set, only highlight the model in the matching provider group. */
  selectedProviderId?: string | null;
}

function ModelStatusBadge({
  model,
  onDownload,
  isDownloadPending,
}: {
  model: LlmModel;
  onDownload: (id: string) => void;
  isDownloadPending: boolean;
}) {
  const t = useThemeTokens();

  if (!model.download_status) return null;

  if (model.download_status === "cached") {
    return (
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: t.success,
          flexShrink: 0,
        }}
        title="Downloaded"
      />
    );
  }

  if (model.download_status === "downloading") {
    return (
      <span
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          fontSize: 11,
          color: t.textDim,
          flexShrink: 0,
        }}
      >
        <Spinner size={12} />
        downloading...
      </span>
    );
  }

  // not_downloaded
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
      {model.size_mb != null && (
        <span style={{ fontSize: 10, color: t.textDim }}>{model.size_mb} MB</span>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDownload(model.id);
        }}
        disabled={isDownloadPending}
        style={{
          background: "none",
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 4,
          padding: "2px 6px",
          cursor: isDownloadPending ? "not-allowed" : "pointer",
          color: t.accent,
          fontSize: 12,
          lineHeight: 1,
          display: "flex",
          alignItems: "center",
          opacity: isDownloadPending ? 0.5 : 1,
        }}
        title="Download model"
      >
        ↓
      </button>
    </span>
  );
}

function Spinner({ size = 14 }: { size?: number }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: size,
        height: size,
        border: "2px solid rgba(255,255,255,0.15)",
        borderTopColor: "rgba(255,255,255,0.6)",
        borderRadius: "50%",
        animation: "llm-dropdown-spin 0.8s linear infinite",
        flexShrink: 0,
      }}
    />
  );
}

// Inject keyframes once
if (typeof document !== "undefined") {
  const styleId = "llm-dropdown-spinner-style";
  if (!document.getElementById(styleId)) {
    const style = document.createElement("style");
    style.id = styleId;
    style.textContent = `@keyframes llm-dropdown-spin { to { transform: rotate(360deg); } }`;
    document.head.appendChild(style);
  }
}

/**
 * Model picker dropdown that renders into a portal (document.body)
 * to avoid any z-index / overflow clipping from parent ScrollViews.
 */
export function LlmModelDropdown({
  value,
  onChange,
  placeholder = "Select model...",
  label,
  allowClear = true,
  anchor = "bottom",
  variant = "llm",
  selectedProviderId,
}: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [pos, setPos] = useState({ top: 0, left: 0, bottom: 0, width: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const llmQuery = useModelGroups();
  const embeddingQuery = useEmbeddingModelGroups();
  const { data: groups, isLoading } = variant === "embedding" ? embeddingQuery : llmQuery;
  const downloadMutation = useDownloadEmbeddingModel();
  const t = useThemeTokens();

  // Measure trigger position for portal dropdown
  const openDropdown = useCallback(() => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({
        top: rect.bottom + 4,
        left: rect.left,
        bottom: window.innerHeight - rect.top + 4,
        width: rect.width,
      });
    }
    setOpen(true);
    setSearch("");
  }, [anchor]);

  const filteredGroups = groups
    ?.map((g) => ({
      ...g,
      models: g.models.filter(
        (m) =>
          !search ||
          m.id.toLowerCase().includes(search.toLowerCase()) ||
          m.display.toLowerCase().includes(search.toLowerCase())
      ),
    }))
    .filter((g) => g.models.length > 0);

  const handleModelClick = (model: LlmModel, providerId?: string | null) => {
    // Don't select models that are currently downloading
    if (model.download_status === "downloading") return;
    onChange(model.id, providerId);
    setOpen(false);
  };

  return (
    <div style={{ position: "relative" }}>
      {label && (
        <div style={{ color: t.textDim, fontSize: 12, marginBottom: 4 }}>{label}</div>
      )}

      {/* Trigger button */}
      <div
        ref={triggerRef}
        onClick={openDropdown}
        style={{
          display: "flex",
          alignItems: "center",
          background: t.inputBg,
          border: `1px solid ${t.inputBorder}`,
          borderRadius: 8,
          padding: "7px 12px",
          cursor: "pointer",
          gap: 8,
        }}
      >
        <span style={{ flex: 1, fontSize: 13, color: value ? t.text : t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {value || placeholder}
        </span>
        {allowClear && value ? (
          <span
            onClick={(e) => { e.stopPropagation(); onChange(""); }}
            style={{ color: t.textMuted, cursor: "pointer", fontSize: 14, lineHeight: 1 }}
          >
            ✕
          </span>
        ) : (
          <span style={{ color: t.textDim, fontSize: 10 }}>▾</span>
        )}
      </div>

      {/* Portal dropdown — rendered into document.body */}
      {open && typeof document !== "undefined" &&
        (() => {
          const ReactDOM = require("react-dom");
          return ReactDOM.createPortal(
            <>
              {/* Backdrop */}
              <div
                onClick={() => setOpen(false)}
                style={{ position: "fixed", inset: 0, zIndex: 50000 }}
              />
              {/* Dropdown panel */}
              <div
                style={{
                  position: "fixed",
                  ...(anchor === "top"
                    ? { bottom: pos.bottom, left: pos.left }
                    : { top: pos.top, left: pos.left }),
                  width: Math.max(pos.width, 320),
                  maxHeight: 340,
                  zIndex: 50001,
                  background: t.surfaceRaised,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 10,
                  boxShadow: "0 12px 40px rgba(0,0,0,0.5)",
                  display: "flex",
                  flexDirection: "column",
                  overflow: "hidden",
                }}
              >
                {/* Search */}
                <div style={{ padding: "10px 12px", borderBottom: `1px solid ${t.surfaceBorder}` }}>
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search models..."
                    autoFocus
                    style={{
                      width: "100%",
                      background: t.inputBg,
                      border: `1px solid ${t.surfaceBorder}`,
                      borderRadius: 6,
                      padding: "6px 10px",
                      color: t.inputText,
                      fontSize: 13,
                      outline: "none",
                    }}
                    onFocus={(e) => { (e.target as HTMLInputElement).style.borderColor = t.accent; }}
                    onBlur={(e) => { (e.target as HTMLInputElement).style.borderColor = t.surfaceBorder; }}
                  />
                </div>

                {/* Model list */}
                <div style={{ flex: 1, overflowY: "auto" }}>
                  {isLoading ? (
                    <div style={{ padding: 16, color: t.textDim, fontSize: 13 }}>Loading models...</div>
                  ) : filteredGroups?.length === 0 ? (
                    <div style={{ padding: 16, color: t.textDim, fontSize: 13, textAlign: "center" }}>No models found</div>
                  ) : (
                    filteredGroups?.map((group) => (
                      <div key={group.provider_name}>
                        <div style={{
                          padding: "6px 12px",
                          background: t.surfaceOverlay,
                          fontSize: 10,
                          fontWeight: 600,
                          color: t.textDim,
                          letterSpacing: "0.05em",
                          textTransform: "uppercase",
                          position: "sticky",
                          top: 0,
                        }}>
                          {group.provider_name}
                        </div>
                        {group.models.map((model) => {
                          const isDownloading = model.download_status === "downloading";
                          const isSelected = model.id === value && (
                            selectedProviderId === undefined ||
                            (group.provider_id ?? null) === (selectedProviderId ?? null)
                          );
                          return (
                            <div
                              key={model.id}
                              onClick={() => handleModelClick(model, group.provider_id ?? null)}
                              onMouseEnter={(e) => {
                                if (!isDownloading) {
                                  (e.currentTarget as HTMLElement).style.background = t.surfaceOverlay;
                                }
                              }}
                              onMouseLeave={(e) => {
                                (e.currentTarget as HTMLElement).style.background =
                                  isSelected ? t.accentSubtle : "transparent";
                              }}
                              style={{
                                padding: "8px 12px",
                                cursor: isDownloading ? "default" : "pointer",
                                background: isSelected ? t.accentSubtle : "transparent",
                                opacity: isDownloading ? 0.6 : 1,
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                              }}
                            >
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, color: isSelected ? t.accent : t.text }}>
                                  {model.id}
                                </div>
                                {model.display !== model.id && (
                                  <div style={{ fontSize: 11, color: t.textDim, marginTop: 1 }}>
                                    {model.display}
                                  </div>
                                )}
                              </div>
                              <ModelStatusBadge
                                model={model}
                                onDownload={(id) => downloadMutation.mutate(id)}
                                isDownloadPending={downloadMutation.isPending}
                              />
                            </div>
                          );
                        })}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </>,
            document.body
          );
        })()
      }
    </div>
  );
}
