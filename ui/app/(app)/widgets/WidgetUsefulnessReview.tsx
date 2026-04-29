import { AlertTriangle, Bot, CheckCircle2, Clock3, Eye, LayoutDashboard, MessageSquare, RefreshCw, Search, Settings, ShieldCheck, Sparkles, X } from "lucide-react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { useState } from "react";
import type {
  WidgetUsefulnessAssessment,
  WidgetAgencyReceipt,
  WidgetUsefulnessRecommendation,
  WidgetUsefulnessSeverity,
  WidgetUsefulnessStatus,
} from "@/src/types/api";
import { useChannelWidgetAgencyReceipts, useChannelWidgetUsefulness } from "@/src/api/hooks/useWidgetUsefulness";
import { Spinner } from "@/src/components/shared/Spinner";

function statusTone(status?: WidgetUsefulnessStatus | null): {
  label: string;
  icon: ReactNode;
  className: string;
} {
  if (status === "action_required") {
    return {
      label: "Action required",
      icon: <AlertTriangle size={14} />,
      className: "bg-danger/10 text-danger-muted",
    };
  }
  if (status === "needs_attention") {
    return {
      label: "Needs attention",
      icon: <AlertTriangle size={14} />,
      className: "bg-warning/10 text-warning-muted",
    };
  }
  if (status === "has_suggestions") {
    return {
      label: "Suggestions",
      icon: <Sparkles size={14} />,
      className: "bg-accent/10 text-accent",
    };
  }
  return {
    label: "Healthy",
    icon: <CheckCircle2 size={14} />,
    className: "bg-success/10 text-success",
  };
}

function severityClass(severity: WidgetUsefulnessSeverity): string {
  if (severity === "high") return "bg-danger/10 text-danger-muted";
  if (severity === "medium") return "bg-warning/10 text-warning-muted";
  if (severity === "low") return "bg-accent/10 text-accent";
  return "bg-surface-overlay text-text-muted";
}

function surfaceIcon(surface: string) {
  if (surface === "chat") return <MessageSquare size={12} />;
  if (surface === "project") return <Sparkles size={12} />;
  return <LayoutDashboard size={12} />;
}

function Pill({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${className || "bg-surface-overlay text-text-muted"}`}>
      {children}
    </span>
  );
}

function evidenceChips(rec: WidgetUsefulnessRecommendation) {
  const chips: string[] = [];
  const ev = rec.evidence || {};
  if (Array.isArray(ev.pin_ids)) chips.push(`${ev.pin_ids.length} pins`);
  if (Array.isArray(ev.labels)) chips.push(`${ev.labels.length} labels`);
  if (typeof ev.zone === "string") chips.push(`zone:${ev.zone}`);
  if (typeof ev.layout_mode === "string") chips.push(`layout:${ev.layout_mode}`);
  if (typeof ev.exported_count === "number") chips.push(`${ev.exported_count} exported`);
  if (typeof ev.export_enabled_count === "number") chips.push(`${ev.export_enabled_count} export-enabled`);
  if (Array.isArray(ev.action_ids)) chips.push(`${ev.action_ids.length} actions`);
  if (ev.health && typeof ev.health === "object" && "status" in ev.health) {
    chips.push(`health:${String((ev.health as { status?: unknown }).status)}`);
  }
  return chips.slice(0, 5);
}

function topFinding(assessment?: WidgetUsefulnessAssessment | null) {
  return assessment?.recommendations?.[0] ?? null;
}

function actionLabel(action: string): string {
  return action.replace(/_/g, " ");
}

function formatReceiptTime(value?: string | null): string {
  if (!value) return "recently";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "recently";
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function receiptPinLabel(receipt: WidgetAgencyReceipt): string | null {
  const afterPins = (receipt.after_state as { pins?: unknown }).pins;
  const beforePins = (receipt.before_state as { pins?: unknown }).pins;
  const pins = Array.isArray(afterPins) && afterPins.length ? afterPins : beforePins;
  if (!Array.isArray(pins) || !pins.length) return null;
  const labels = pins
    .map((pin) => {
      if (!pin || typeof pin !== "object") return null;
      const label = (pin as { label?: unknown; tool_name?: unknown }).label ?? (pin as { tool_name?: unknown }).tool_name;
      return typeof label === "string" && label.trim() ? label.trim() : null;
    })
    .filter(Boolean) as string[];
  if (!labels.length) return null;
  return labels.slice(0, 2).join(", ") + (labels.length > 2 ? ` +${labels.length - 2}` : "");
}

function BotWidgetChangeList({
  receipts,
  loading,
}: {
  receipts: WidgetAgencyReceipt[];
  loading?: boolean;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-md bg-surface-raised/40 px-3 py-3" data-testid="widget-agency-receipts">
      <div className="flex items-center justify-between gap-2">
        <div className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-text">
          <Bot size={13} />
          Recent bot widget changes
        </div>
        {loading && <Spinner />}
      </div>
      {!loading && receipts.length === 0 && (
        <div className="text-[12px] leading-relaxed text-text-dim">No bot-applied widget changes recorded.</div>
      )}
      {receipts.slice(0, 6).map((receipt) => (
        <div key={receipt.id} className="rounded-md bg-surface-overlay/30 px-2.5 py-2" data-testid="widget-agency-receipt-row">
          <div className="flex flex-wrap items-center gap-1.5">
            <Pill className="bg-accent/10 text-accent">{actionLabel(receipt.action)}</Pill>
            {receiptPinLabel(receipt) && <Pill>{receiptPinLabel(receipt)}</Pill>}
            <span className="inline-flex items-center gap-1 text-[11px] text-text-dim">
              <Clock3 size={11} />
              {formatReceiptTime(receipt.created_at)}
            </span>
          </div>
          <div className="mt-1 text-[12px] leading-relaxed text-text-muted">{receipt.summary}</div>
          {receipt.reason && <div className="mt-1 text-[12px] leading-relaxed text-text-dim">Reason: {receipt.reason}</div>}
        </div>
      ))}
    </div>
  );
}

export function WidgetUsefulnessToolbarButton({
  channelId,
  checkingHealth,
  onCheckHealth,
  onFocusPin,
  onEditPin,
  onEditLayout,
  onOpenSettings,
}: {
  channelId: string;
  checkingHealth?: boolean;
  onCheckHealth?: () => void;
  onFocusPin?: (pinId: string) => void;
  onEditPin?: (pinId: string) => void;
  onEditLayout?: () => void;
  onOpenSettings?: () => void;
}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const query = useChannelWidgetUsefulness(channelId);
  const assessment = query.data;
  const tone = statusTone(assessment?.status);
  const findingCount = assessment?.recommendations.length ?? 0;
  const label = findingCount > 0 ? `${findingCount} widget proposals` : "Widget proposals";

  return (
    <>
      <button
        type="button"
        onClick={() => setDrawerOpen(true)}
        className={
          "inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[12px] font-medium transition-colors hover:bg-surface-overlay " +
          (findingCount > 0 ? "text-warning-muted hover:text-warning-muted" : "text-text-muted hover:text-text")
        }
        data-testid="widget-usefulness-review-trigger"
        aria-label="Open dashboard widget proposals"
        title={assessment?.summary ?? "Open dashboard widget proposals"}
      >
        {query.isLoading ? <Spinner /> : tone.icon}
        <span className="hidden lg:inline">{label}</span>
      </button>
      {drawerOpen && (
        <WidgetUsefulnessDrawer
          channelId={channelId}
          assessment={assessment ?? null}
          isLoading={query.isLoading}
          error={query.error}
          onRefresh={() => void query.refetch()}
          onCheckHealth={onCheckHealth}
          checkingHealth={checkingHealth}
          onClose={() => setDrawerOpen(false)}
          onFocusPin={onFocusPin}
          onEditPin={onEditPin}
          onEditLayout={onEditLayout}
          onOpenSettings={onOpenSettings}
        />
      )}
    </>
  );
}

export function WidgetUsefulnessSettingsSummary({ channelId }: { channelId: string }) {
  const query = useChannelWidgetUsefulness(channelId);
  const receiptsQuery = useChannelWidgetAgencyReceipts(channelId, 3);
  const assessment = query.data;
  const finding = topFinding(assessment);
  const tone = statusTone(assessment?.status);
  const latestReceipt = receiptsQuery.data?.receipts?.[0] ?? null;

  return (
    <div className="mt-4 flex flex-col gap-3 rounded-md bg-surface-raised/45 px-3 py-3" data-testid="channel-widget-usefulness-settings-summary">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone.className}`}>
            {query.isLoading ? <Spinner /> : tone.icon}
            {query.isLoading ? "Checking" : tone.label}
          </span>
          <span className="text-[13px] font-semibold text-text">Widget usefulness</span>
        </div>
        <button
          type="button"
          onClick={() => void query.refetch()}
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text"
        >
          <RefreshCw size={12} className={query.isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>
      <p className="text-[12px] leading-relaxed text-text-dim">
        {finding ? finding.reason : assessment?.summary ?? "Check dashboard coverage, hidden chat surfaces, context export, and widget health from the dashboard."}
      </p>
      {assessment && (
        <div className="flex flex-wrap gap-1.5">
          <Pill>{assessment.pin_count} pins</Pill>
          <Pill>{assessment.chat_visible_pin_count} chat-visible</Pill>
          <Pill>layout:{assessment.layout_mode}</Pill>
          <Pill>{assessment.widget_agency_mode === "propose_and_fix" ? "propose + fix" : "propose"}</Pill>
          {assessment.recommendations.length > 0 && <Pill className="bg-warning/10 text-warning-muted">{assessment.recommendations.length} widget proposals</Pill>}
        </div>
      )}
      {latestReceipt && (
        <div className="rounded-md bg-surface-overlay/30 px-2.5 py-2" data-testid="widget-agency-latest-receipt">
          <div className="flex flex-wrap items-center gap-1.5">
            <Pill className="bg-accent/10 text-accent">bot widget change</Pill>
            <Pill>{actionLabel(latestReceipt.action)}</Pill>
            <span className="text-[11px] text-text-dim">{formatReceiptTime(latestReceipt.created_at)}</span>
          </div>
          <div className="mt-1 text-[12px] leading-relaxed text-text-muted">{latestReceipt.summary}</div>
        </div>
      )}
      {query.error && (
        <span className="text-[12px] text-danger">
          {query.error instanceof Error ? query.error.message : "Failed to load widget usefulness."}
        </span>
      )}
    </div>
  );
}

function WidgetUsefulnessDrawer({
  channelId,
  assessment,
  isLoading,
  error,
  onRefresh,
  onCheckHealth,
  checkingHealth,
  onClose,
  onFocusPin,
  onEditPin,
  onEditLayout,
  onOpenSettings,
}: {
  channelId: string;
  assessment: WidgetUsefulnessAssessment | null;
  isLoading: boolean;
  error: unknown;
  onRefresh: () => void;
  onCheckHealth?: () => void;
  checkingHealth?: boolean;
  onClose: () => void;
  onFocusPin?: (pinId: string) => void;
  onEditPin?: (pinId: string) => void;
  onEditLayout?: () => void;
  onOpenSettings?: () => void;
}) {
  const receiptsQuery = useChannelWidgetAgencyReceipts(channelId, 8);
  if (typeof document === "undefined") return null;
  const recommendations = assessment?.recommendations ?? [];
  const tone = statusTone(assessment?.status);
  const errorMessage = error instanceof Error ? error.message : error ? "Failed to load widget usefulness." : null;

  return createPortal(
    <div className="fixed inset-0 z-[10000] flex justify-end" data-testid="widget-usefulness-review-drawer">
      <button type="button" aria-label="Close widget proposals" className="absolute inset-0 bg-black/35" onClick={onClose} />
      <div className="relative flex h-full w-full max-w-[760px] flex-col border-l border-surface-border bg-surface shadow-2xl">
        <div className="flex min-h-[68px] items-start justify-between gap-3 border-b border-surface-border px-5 py-4">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">Widget proposals</div>
            <h2 className="mt-1 truncate text-[16px] font-semibold text-text">{assessment?.channel_name ?? "Channel dashboard"}</h2>
            <p className="mt-1 max-w-[62ch] text-[12px] leading-relaxed text-text-dim">
              Usefulness, visibility, prompt context, and health signals. Bot edits follow this channel's widget agency setting.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 shrink-0 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-5">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-3 rounded-md bg-surface-raised/45 px-3 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold ${tone.className}`}>
                  {isLoading ? <Spinner /> : tone.icon}
                  {isLoading ? "Checking" : tone.label}
                </span>
                {assessment && (
                  <>
                    <Pill>{assessment.pin_count} pins</Pill>
                    <Pill>{assessment.chat_visible_pin_count} chat-visible</Pill>
                    <Pill>layout:{assessment.layout_mode}</Pill>
                    <Pill>{assessment.widget_agency_mode === "propose_and_fix" ? "propose + fix" : "propose"}</Pill>
                    {assessment.project_scope_available && <Pill><Sparkles size={11} /> Project</Pill>}
                  </>
                )}
              </div>
              <p className="text-[12px] leading-relaxed text-text-dim">
                {assessment?.summary ?? "Loading widget usefulness assessment..."}
              </p>
              {errorMessage && <p className="text-[12px] text-danger">{errorMessage}</p>}
            </div>

            <BotWidgetChangeList
              receipts={receiptsQuery.data?.receipts ?? []}
              loading={receiptsQuery.isLoading}
            />

            {!isLoading && !errorMessage && recommendations.length === 0 && (
              <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/30 px-4 py-8 text-center text-[13px] text-text-dim">
                No actionable widget proposals.
              </div>
            )}

            {recommendations.map((rec, index) => (
              <div
                key={`${rec.type}-${rec.pin_id ?? "dashboard"}-${index}`}
                className="flex flex-col gap-3 rounded-md bg-surface-raised/40 px-3 py-3"
                data-testid="widget-usefulness-finding"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Pill className={severityClass(rec.severity)}>{rec.severity}</Pill>
                      <Pill>{surfaceIcon(rec.surface)} {rec.surface}</Pill>
                      <Pill>{rec.type.replace(/_/g, " ")}</Pill>
                      {rec.requires_policy_decision && <Pill className="bg-warning/10 text-warning-muted">policy decision</Pill>}
                    </div>
                    <div className="mt-2 text-[13px] font-semibold text-text">{rec.label ?? "Dashboard"}</div>
                  </div>
                </div>
                <p className="text-[12px] leading-relaxed text-text-muted">{rec.reason}</p>
                <p className="text-[12px] leading-relaxed text-text-dim">{rec.suggested_next_action}</p>
                {evidenceChips(rec).length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {evidenceChips(rec).map((chip) => <Pill key={chip}>{chip}</Pill>)}
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-1.5">
                  {rec.pin_id && onFocusPin && (
                    <button type="button" onClick={() => { onFocusPin(rec.pin_id!); onClose(); }} className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text">
                      <Eye size={12} />
                      Focus pin
                    </button>
                  )}
                  {rec.pin_id && onEditPin && (
                    <button type="button" onClick={() => { onEditPin(rec.pin_id!); onClose(); }} className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text">
                      <Settings size={12} />
                      Edit pin
                    </button>
                  )}
                  {onEditLayout && (
                    <button type="button" onClick={() => { onEditLayout(); onClose(); }} className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text">
                      <LayoutDashboard size={12} />
                      Edit layout
                    </button>
                  )}
                  {onOpenSettings && (
                    <button type="button" onClick={onOpenSettings} className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium text-accent transition-colors hover:bg-accent/[0.08]">
                      <Settings size={12} />
                      Channel settings
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-border px-5 py-3">
          <p className="max-w-[48ch] text-[11px] leading-relaxed text-text-dim">
            In Propose mode, bots publish widget proposals only. In Propose + fix mode, approved bot tasks can apply safe dashboard changes and record bot widget change receipts.
          </p>
          <div className="flex items-center gap-1.5">
            {onCheckHealth && (
              <button type="button" onClick={onCheckHealth} disabled={checkingHealth} className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[12px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text disabled:opacity-50">
                <ShieldCheck size={13} className={checkingHealth ? "animate-pulse" : ""} />
                Check health
              </button>
            )}
            <button type="button" onClick={onRefresh} className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[12px] font-medium text-text-muted transition-colors hover:bg-surface-overlay hover:text-text">
              <RefreshCw size={13} />
              Refresh
            </button>
            <button type="button" onClick={onClose} className="inline-flex h-8 items-center rounded-md px-2.5 text-[12px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]">
              Done
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
