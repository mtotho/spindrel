import { Link } from "react-router-dom";
import { ChevronRight, Radar } from "lucide-react";

import {
  isActiveAttentionItem,
  useWorkspaceAttention,
  type AttentionSeverity,
  type WorkspaceAttentionItem,
} from "../../../api/hooks/useWorkspaceAttention";
import { attentionHubHref, attentionItemHref } from "../../../lib/hubRoutes";
import { contextualNavigationState } from "../../../lib/contextualNavigation";
import { StatusBadge } from "../../shared/SettingsControls";
import { SectionHeading } from "./SectionHeading";

const SEVERITY_RANK: Record<AttentionSeverity, number> = {
  critical: 4,
  error: 3,
  warning: 2,
  info: 1,
};

function severityVariant(s: AttentionSeverity): "danger" | "warning" | "info" {
  if (s === "critical" || s === "error") return "danger";
  if (s === "warning") return "warning";
  return "info";
}

const MAX_ITEMS = 4;
const HUB_BACK_STATE = contextualNavigationState("/", "Home");

/**
 * Active workspace Attention items sorted by severity. Renders nothing
 * when there's nothing to act on. Tapping an item jumps to its target
 * channel (or bot detail page when the item is bot-scoped).
 */
export function AttentionSection({
  onOpenItem,
  onOpenHub,
}: {
  onOpenItem?: (item: WorkspaceAttentionItem) => void;
  onOpenHub?: () => void;
}) {
  const { data } = useWorkspaceAttention();
  const active = (data ?? []).filter(isActiveAttentionItem);
  if (active.length === 0) return null;

  const sorted = [...active].sort(
    (a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity],
  );
  const visible = sorted.slice(0, MAX_ITEMS);
  const overflow = active.length - visible.length;

  return (
    <section className="flex flex-col gap-2">
      <SectionHeading icon={<Radar size={14} />} label="Attention" count={active.length} />
      <div className="flex flex-col gap-1">
        {visible.map((item) => (
          <Link
            key={item.id}
            to={attentionItemHref(item)}
            state={HUB_BACK_STATE}
            onClick={
              onOpenItem
                ? (event) => {
                    event.preventDefault();
                    onOpenItem(item);
                  }
                : undefined
            }
            className="group flex min-h-[56px] items-start gap-3 rounded-md bg-surface-raised/40 px-3 py-2.5 transition-colors hover:bg-surface-overlay/45"
          >
            <div className="mt-0.5">
              <StatusBadge label={item.severity} variant={severityVariant(item.severity)} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-text">{item.title}</div>
              <div className="truncate text-xs text-text-dim">
                {item.channel_name || item.message || item.target_kind}
              </div>
            </div>
            <ChevronRight
              size={14}
              className="mt-1 shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100"
            />
          </Link>
        ))}
        {overflow > 0 ? (
          <Link
            to={attentionHubHref()}
            state={HUB_BACK_STATE}
            onClick={
              onOpenHub
                ? (event) => {
                    event.preventDefault();
                    onOpenHub();
                  }
                : undefined
            }
            className="px-3 py-1.5 text-[11px] text-text-dim hover:text-text"
          >
            +{overflow} more in Attention Hub
          </Link>
        ) : null}
      </div>
    </section>
  );
}
