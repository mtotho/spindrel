import { useState } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useHudData, type ActiveHud } from "@/src/api/hooks/useChatHud";
import { HudItemRenderer } from "./HudItemRenderer";
import { resolveHudIcon } from "./hudIcons";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { ChevronLeft, ChevronRight } from "lucide-react";

/**
 * Collapsible panel on the right side of chat.
 * Supports either data-driven cards (endpoint) or iframe (iframe_path).
 */
export function HudSidePanel({ hud }: { hud: ActiveHud }) {
  const t = useThemeTokens();
  const [collapsed, setCollapsed] = useState(hud.widget.collapsed_by_default !== false);
  const width = hud.widget.width ?? 320;

  const isIframe = !!hud.widget.iframe_path;
  const { data, isLoading } = useHudData(
    hud.integrationId,
    isIframe ? undefined : hud.widget.endpoint,
    hud.widget.poll_interval ?? 60,
    !isIframe && !collapsed,
  );

  const queryKey = ["hud-data", hud.integrationId, hud.widget.endpoint ?? ""];
  const LabelIcon = resolveHudIcon(hud.widget.icon);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        aria-label="Expand panel"
        style={{
          width: 32,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: t.surfaceRaised,
          border: "none",
          borderLeft: `1px solid ${t.surfaceBorder}`,
          cursor: "pointer",
          padding: 0,
          flexShrink: 0,
        }}
      >
        <ChevronLeft size={14} color={t.textDim} />
        <span style={{
          fontSize: 10,
          color: t.textDim,
          writingMode: "vertical-lr",
          transform: "rotate(180deg)",
          marginTop: 8,
        }}>
          {hud.widget.label ?? hud.widget.id}
        </span>
      </button>
    );
  }

  return (
    <div style={{
      width,
      borderLeft: `1px solid ${t.surfaceBorder}`,
      backgroundColor: t.surfaceRaised,
      display: "flex",
      flexDirection: "column",
      flexShrink: 0,
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "8px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <LabelIcon size={13} color={t.textDim} />
          <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
            {hud.widget.label ?? hud.widget.id}
          </span>
        </div>
        <button
          onClick={() => setCollapsed(true)}
          className="header-icon-btn"
          aria-label="Collapse panel"
          style={{ background: "none", border: "none", cursor: "pointer", padding: 6, borderRadius: 4 }}
        >
          <ChevronRight size={14} color={t.textDim} />
        </button>
      </div>

      {/* Content */}
      {isIframe ? (
        <IframeContent integrationId={hud.integrationId} iframePath={hud.widget.iframe_path!} />
      ) : isLoading && !data ? (
        <div style={{ padding: 16, display: "flex", justifyContent: "center" }}>
          <div className="chat-spinner" />
        </div>
      ) : data?.visible ? (
        <div style={{ flex: 1, overflow: "auto", padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
          {data.items.map((item, i) => (
            <HudItemRenderer key={i} item={item} hudQueryKey={queryKey} vertical />
          ))}
        </div>
      ) : (
        <div style={{ padding: 12 }}>
          <span style={{ fontSize: 12, color: t.textDim }}>No data</span>
        </div>
      )}
    </div>
  );
}

function IframeContent({ integrationId, iframePath }: { integrationId: string; iframePath: string }) {
  const { serverUrl } = useAuthStore.getState();
  const token = getAuthToken();
  const src = `${serverUrl}/integrations/${integrationId}${iframePath}${iframePath.includes("?") ? "&" : "?"}tkn=${encodeURIComponent(token || "")}`;

  return (
    <iframe
      src={src}
      title="HUD panel content"
      style={{
        border: "none",
        width: "100%",
        flex: 1,
        minHeight: 300,
      }}
    />
  );
}
