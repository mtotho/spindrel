import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Check,
  XCircle,
  Loader2,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/src/lib/cn";
import { useResolveStep } from "@/src/api/hooks/useResolveStep";

// ---------------------------------------------------------------------------
// Shared renderer for `widget_envelope.template.kind === "approval_review"`
// steps. Used inline in the chat anchor (TaskRunEnvelope) AND in the side-rail
// FindingsPanel so both surfaces render, style, and resolve identically.
// ---------------------------------------------------------------------------

export interface Evidence {
  correlation_id?: string;
  bot_id?: string;
  signal?: string;
}

export interface ProposalScope {
  target_kind?: "skills" | "tools" | "bots" | string;
  target_id?: string;
  bots_affected?: string[];
}

export interface ProposalItem {
  id: string;
  label?: string;
  rationale?: string;
  diff_preview?: string;
  scope?: ProposalScope | string;
  target_path?: string;
  target_method?: string;
  evidence?: Evidence[];
  [k: string]: any;
}

type Decision = "approve" | "reject" | undefined;

// ---------------------------------------------------------------------------
// Scope chip — primary identifier for each proposal. Colour-codes by kind.
// ---------------------------------------------------------------------------

function scopeChipClasses(kind: string | undefined): string {
  switch (kind) {
    case "skills":
      return "bg-teal-500/10 text-teal-400 border-teal-500/30";
    case "tools":
      return "bg-purple-500/10 text-purple-400 border-purple-500/30";
    case "bots":
      return "bg-amber-500/10 text-amber-400 border-amber-500/30";
    default:
      return "bg-surface-overlay text-text-dim border-surface-border";
  }
}

function scopeLabel(kind: string | undefined): string {
  switch (kind) {
    case "skills":
      return "skill";
    case "tools":
      return "tool";
    case "bots":
      return "bot";
    default:
      return kind || "patch";
  }
}

function resolveScope(item: ProposalItem): { kind?: string; targetId?: string } {
  const s = item.scope;
  if (s && typeof s === "object") {
    return { kind: s.target_kind, targetId: s.target_id };
  }
  if (typeof s === "string") return { kind: s };
  return {};
}

// ---------------------------------------------------------------------------
// Single-proposal row
// ---------------------------------------------------------------------------

function ProposalRow({
  item,
  decision,
  onDecide,
}: {
  item: ProposalItem;
  decision: Decision;
  onDecide: (d: "approve" | "reject") => void;
}) {
  const [diffOpen, setDiffOpen] = useState(false);
  const { kind, targetId } = resolveScope(item);
  const label = item.label || targetId || item.id;
  const summary = item.rationale || "";
  const diff = item.diff_preview || "";
  const evidence: Evidence[] = Array.isArray(item.evidence) ? item.evidence : [];
  const tracedEvidence = evidence.filter((e) => e.correlation_id && e.correlation_id.length > 0);
  const untracedEvidence = evidence.filter((e) => !e.correlation_id);

  return (
    <div
      className={cn(
        "rounded-md border p-2.5 flex flex-col gap-2 transition-colors",
        decision === "approve" && "border-emerald-500/50 bg-emerald-500/5",
        decision === "reject" && "border-red-500/50 bg-red-500/5",
        !decision && "border-surface-border bg-surface",
      )}
    >
      {/* Row 1: scope chip + target + actions */}
      <div className="flex flex-row items-start gap-2">
        <div className="flex flex-col gap-1 min-w-0 flex-1">
          <div className="flex flex-row items-center gap-1.5 min-w-0 flex-wrap">
            {kind && (
              <span
                className={cn(
                  "inline-flex items-center px-1.5 py-0.5 rounded border text-[10px] font-semibold uppercase tracking-wider shrink-0",
                  scopeChipClasses(kind),
                )}
              >
                {scopeLabel(kind)}
              </span>
            )}
            <span className="text-xs font-semibold text-text truncate">{label}</span>
          </div>
          {item.target_path && (
            <span className="text-[10px] text-text-dim/80 font-mono truncate">
              {item.target_method || "PATCH"} {item.target_path}
            </span>
          )}
          {summary && (
            <p className="text-[11px] text-text-dim leading-snug">
              {summary}
            </p>
          )}
        </div>
        <div className="flex flex-row gap-1 shrink-0">
          <button
            onClick={() => onDecide("approve")}
            aria-label="Approve"
            className={cn(
              "inline-flex items-center justify-center w-7 h-7 rounded transition-colors",
              decision === "approve"
                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/50"
                : "bg-surface-raised text-text-dim border border-surface-border hover:bg-emerald-500/10 hover:text-emerald-400",
            )}
          >
            <Check size={12} />
          </button>
          <button
            onClick={() => onDecide("reject")}
            aria-label="Reject"
            className={cn(
              "inline-flex items-center justify-center w-7 h-7 rounded transition-colors",
              decision === "reject"
                ? "bg-red-500/20 text-red-400 border border-red-500/50"
                : "bg-surface-raised text-text-dim border border-surface-border hover:bg-red-500/10 hover:text-red-400",
            )}
          >
            <XCircle size={12} />
          </button>
        </div>
      </div>

      {/* Row 2: evidence chips (trace-id links + untraced signals) */}
      {evidence.length > 0 && (
        <div className="flex flex-row flex-wrap items-center gap-1 text-[10px]">
          <span className="text-text-dim uppercase tracking-wider">evidence:</span>
          {tracedEvidence.map((e, i) => (
            <Link
              key={`t-${i}`}
              to={`/admin/traces/${e.correlation_id}`}
              title={e.signal || e.correlation_id}
              className="inline-flex items-center px-1.5 py-0.5 rounded bg-surface-overlay/60
                         border border-surface-border font-mono text-accent
                         hover:bg-accent/10 hover:border-accent/40 transition-colors"
            >
              {(e.correlation_id || "").slice(0, 8)}
            </Link>
          ))}
          {untracedEvidence.map((e, i) => (
            <span
              key={`u-${i}`}
              title={e.signal}
              className="inline-flex items-center max-w-[240px] px-1.5 py-0.5 rounded
                         bg-surface-overlay/40 border border-surface-border
                         text-text-dim truncate"
            >
              {e.signal || "signal"}
            </span>
          ))}
        </div>
      )}

      {/* Row 3: diff expander */}
      {diff && (
        <div className="flex flex-col gap-1">
          <button
            onClick={() => setDiffOpen((v) => !v)}
            className="self-start inline-flex items-center gap-1 text-[10px] text-text-dim
                       hover:text-text uppercase tracking-wider"
          >
            {diffOpen ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
            Diff
          </button>
          {diffOpen && (
            <pre className="m-0 rounded bg-surface-overlay/60 border border-surface-border
                           px-2 py-1.5 font-mono text-[10.5px] text-text-muted
                           whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
              {diff}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component — renders the full approval widget given a single envelope.
// The caller (chat anchor OR findings panel) supplies the task coordinates.
// ---------------------------------------------------------------------------

export interface InlineApprovalReviewProps {
  taskId: string;
  stepIndex: number;
  widgetEnvelope: Record<string, any> | null | undefined;
  responseSchema: Record<string, any> | null | undefined;
  /** Optional — shown above the proposal list as a pill. Usually pulled from
   *  the step's `title` field when rendered in chat; omit when the enclosing
   *  FindingsPanel card already shows the same header. */
  headline?: string;
}

export function InlineApprovalReview({
  taskId,
  stepIndex,
  widgetEnvelope,
  responseSchema,
  headline,
}: InlineApprovalReviewProps) {
  const schema = responseSchema || {};
  const schemaType = (schema as any).type as "binary" | "multi_item" | undefined;
  const items: ProposalItem[] = useMemo(() => {
    const fromSchema = (schema as any).items;
    if (Array.isArray(fromSchema)) return fromSchema;
    // Fallback: some envelopes carry the proposals under template args.
    const tmpl = (widgetEnvelope as any)?.template;
    const fromTemplate = tmpl?.proposals ?? (widgetEnvelope as any)?.args?.proposals;
    return Array.isArray(fromTemplate) ? fromTemplate : [];
  }, [schema, widgetEnvelope]);

  const [decisions, setDecisions] = useState<Record<string, "approve" | "reject">>({});
  const [binaryDecision, setBinaryDecision] = useState<Decision>(undefined);
  const resolveMut = useResolveStep();

  const approvedCount = Object.values(decisions).filter((d) => d === "approve").length;

  const handleSubmit = () => {
    let response: Record<string, any>;
    if (schemaType === "binary") {
      if (!binaryDecision) return;
      response = { decision: binaryDecision };
    } else {
      response = { ...decisions };
      for (const it of items) {
        if (!response[it.id]) response[it.id] = "reject";
      }
    }
    resolveMut.mutate({ taskId, stepIndex, response });
  };

  const handleSkip = () => {
    resolveMut.mutate({ taskId, stepIndex, response: {} });
  };

  // Empty-proposal multi_item — let the user drain the queue.
  if (schemaType === "multi_item" && items.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        {headline && (
          <div className="text-xs font-semibold text-text">{headline}</div>
        )}
        <div className="text-[11px] text-text-dim italic flex items-center gap-1.5">
          <AlertTriangle size={11} className="text-amber-500" />
          No proposals — the agent step returned an empty list.
        </div>
        <button
          onClick={handleSkip}
          disabled={resolveMut.isPending}
          className="px-2.5 py-1 text-[11px] rounded-md bg-surface-raised border border-surface-border
                     text-text-dim hover:text-text self-start disabled:opacity-50"
        >
          {resolveMut.isPending ? "Resolving..." : "Dismiss"}
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {headline && (
        <div className="text-xs font-semibold text-text">{headline}</div>
      )}

      {schemaType === "binary" ? (
        <div className="flex flex-row gap-1.5">
          <button
            onClick={() => setBinaryDecision("approve")}
            className={cn(
              "flex-1 inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded text-xs font-medium",
              binaryDecision === "approve"
                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/50"
                : "bg-surface-raised text-text-dim border border-surface-border hover:text-text",
            )}
          >
            <Check size={12} /> Approve
          </button>
          <button
            onClick={() => setBinaryDecision("reject")}
            className={cn(
              "flex-1 inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded text-xs font-medium",
              binaryDecision === "reject"
                ? "bg-red-500/20 text-red-400 border border-red-500/50"
                : "bg-surface-raised text-text-dim border border-surface-border hover:text-text",
            )}
          >
            <XCircle size={12} /> Reject
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          {items.map((item) => (
            <ProposalRow
              key={item.id}
              item={item}
              decision={decisions[item.id]}
              onDecide={(d) => setDecisions((s) => ({ ...s, [item.id]: d }))}
            />
          ))}
        </div>
      )}

      {resolveMut.isError && (
        <div className="text-[11px] text-red-400">
          {(resolveMut.error as Error)?.message ?? "Resolve failed"}
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={
          resolveMut.isPending ||
          (schemaType === "binary" ? !binaryDecision : false)
        }
        className="mt-1 px-3 py-1.5 rounded-md bg-accent text-white text-xs font-semibold
                   hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed
                   inline-flex items-center justify-center gap-1.5"
      >
        {resolveMut.isPending && <Loader2 size={12} className="animate-spin" />}
        {schemaType === "multi_item"
          ? `Submit (${approvedCount} approved, ${items.length - approvedCount} rejected)`
          : "Submit"}
      </button>
    </div>
  );
}
