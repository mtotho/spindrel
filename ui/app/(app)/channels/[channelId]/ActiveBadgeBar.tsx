import { useNavigate } from "react-router-dom";
import { FileText, Wrench } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useActivatableIntegrations, useChannelSettings } from "@/src/api/hooks/useChannels";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";

/**
 * Compact horizontal strip showing what's active on this channel:
 * template badge + tool/skill count. Integration badges are deliberately
 * omitted — desktop shows them inline in the ChannelHeader subtitle, and the
 * mobile sub-header stays quieter to match.
 * Clicking a badge navigates to the relevant settings tab.
 */
export function ActiveBadgeBar({ channelId, compact }: { channelId: string; compact?: boolean }) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: settings } = useChannelSettings(channelId);
  const { data: activatable } = useActivatableIntegrations(channelId);
  const { data: templates } = usePromptTemplates(undefined, "workspace_schema");

  const activeIntegrations = activatable?.filter((ig) => ig.activated) ?? [];

  const templateId = settings?.workspace_schema_template_id;
  const template = templateId ? templates?.find((tpl) => tpl.id === templateId) : null;

  // Tool counts from activated integrations
  const totalTools = activeIntegrations.reduce((sum, ig) => sum + (ig.tools?.length ?? 0), 0);

  // Still loading — reserve space with a shimmer placeholder to prevent layout shift
  const isLoading = !settings && !activatable;
  if (isLoading) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          padding: compact ? "4px 12px" : "4px 16px",
          gap: 12,
          flexShrink: 0,
          height: 26,
        }}
      >
        <div className="w-[50px] h-[10px] rounded bg-skeleton/[0.04] animate-pulse" />
        <div className="w-[70px] h-[10px] rounded bg-skeleton/[0.04] animate-pulse" />
      </div>
    );
  }

  // Nothing to show? Don't render the bar.
  // Integration badges are intentionally omitted here to stay consistent with
  // desktop's channel subtitle (the sub-header shouldn't double up on that
  // signal). Template + tool-count are all that remain.
  const hasAnything = template || totalTools > 0;
  if (!hasAnything) return null;

  const nav = (hash: string) => navigate(`/channels/${channelId}/settings#${hash}`);

  const pillStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    background: "none",
    border: "none",
    cursor: "pointer",
    padding: 0,
    whiteSpace: "nowrap",
  };

  const badges = (
    <>
      {/* Template badge */}
      {template && (
        <button onClick={() => nav("workspace")} style={pillStyle}>
          <FileText size={11} color={t.accent} />
          <span style={{ fontSize: 11, color: t.accent, fontWeight: 500, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis" }}>
            {template.name}
          </span>
        </button>
      )}

      {/* Integration badges intentionally omitted on mobile — desktop surfaces
          them inline in the ChannelHeader subtitle, and doubling up here made
          the mobile sub-header noisy without adding information. */}

      {/* Tool/skill counts — inline text, no pill */}
      {totalTools > 0 && (
        <button onClick={() => nav("tools")} style={pillStyle}>
          <Wrench size={10} color={t.textDim} />
          <span style={{ fontSize: 10, color: t.textDim }}>
            {totalTools}
          </span>
        </button>
      )}
    </>
  );

  // Compact mode: horizontal scroll, single row, no wrap
  if (compact) {
    return (
      <div
        className="hide-scrollbar"
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          overflowX: "auto",
          flexShrink: 0,
          maxHeight: 26,
          padding: "4px 12px",
          gap: 12,
          /* border removed — parent wrapper provides the unified bottom border */
        }}
      >
        {badges}
      </div>
    );
  }

  // Default: wrapping row (desktop)
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        padding: "4px 16px",
        gap: 12,
        flexWrap: "wrap",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}
    >
      {badges}
    </div>
  );
}
