import { AlertTriangle, Check, ClipboardCopy, Loader2, Pin, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  checkWidgetAuthoring,
  previewWidgetInline,
  previewWidgetPackage,
  type AuthoringCheckResponse,
  type PreviewEnvelope,
  type ValidationIssue,
} from "@/src/api/hooks/useWidgetPackages";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import { adaptToToolResultEnvelope } from "@/src/components/chat/renderers/resolveEnvelope";
import { useDebouncedValue } from "@/src/hooks/useDebouncedValue";
import { useThemeTokens } from "@/src/theme/tokens";

interface Draft {
  yaml_template: string;
  python_code: string;
  sample_text: string;
  tool_name?: string;
}

interface Props {
  packageId: string | undefined;
  isNew: boolean;
  draft: Draft;
  samplePayload: Record<string, unknown>;
  validationErrors: ValidationIssue[];
  /**
   * Optional pin handler. When provided, a "Pin as card" button appears in the
   * toolbar. The envelope is the one currently rendered (from whichever preview
   * path is active — inline for drafts, package for saved).
   */
  onPin?: (envelope: PreviewEnvelope) => Promise<void>;
  /** Disable pin button even if onPin is set (e.g. tool_name not specified). */
  pinDisabledReason?: string | null;
}

type ViewMode = "rendered" | "raw";
type PinState = "idle" | "pinning" | "success" | "error";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

export function PreviewPane({
  packageId, isNew, draft, samplePayload, validationErrors, onPin, pinDisabledReason,
}: Props) {
  const t = useThemeTokens();
  const [mode, setMode] = useState<ViewMode>("rendered");
  const [envelope, setEnvelope] = useState<PreviewEnvelope | null>(null);
  const [previewErrors, setPreviewErrors] = useState<ValidationIssue[]>([]);
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState(0);
  const [copied, setCopied] = useState(false);
  const [pinState, setPinState] = useState<PinState>("idle");
  const [pinError, setPinError] = useState<string | null>(null);
  const [checkRunning, setCheckRunning] = useState(false);
  const [checkResult, setCheckResult] = useState<AuthoringCheckResponse | null>(null);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [lastCheckSignature, setLastCheckSignature] = useState<string | null>(null);
  const pinRevertTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const debouncedYaml = useDebouncedValue(draft.yaml_template, 500);
  const debouncedPython = useDebouncedValue(draft.python_code, 500);
  const debouncedSample = useDebouncedValue(samplePayload, 500);
  const debouncedToolName = useDebouncedValue(draft.tool_name ?? "", 500);

  const isDraft = isNew || !packageId;
  const blocked = validationErrors.length > 0;
  const hasContent = debouncedYaml.trim().length > 0;
  const currentCheckSignature = useMemo(
    () => JSON.stringify({
      yaml: draft.yaml_template,
      python: draft.python_code,
      sample: samplePayload,
      tool: draft.tool_name ?? "",
    }),
    [draft.yaml_template, draft.python_code, draft.tool_name, samplePayload],
  );
  const checkStale = !!checkResult && lastCheckSignature !== currentCheckSignature;

  useEffect(() => {
    return () => {
      if (pinRevertTimer.current) clearTimeout(pinRevertTimer.current);
    };
  }, []);

  useEffect(() => {
    if (blocked || !hasContent) {
      setEnvelope(null);
      setPreviewErrors([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    const fetch = isDraft
      ? previewWidgetInline({
          yaml_template: debouncedYaml,
          python_code: debouncedPython || null,
          sample_payload: debouncedSample,
          tool_name: debouncedToolName || null,
        })
      : previewWidgetPackage(packageId!, {
          yaml_template: debouncedYaml,
          python_code: debouncedPython || null,
          sample_payload: debouncedSample,
        });
    fetch
      .then((res) => {
        if (cancelled) return;
        if (res.ok) {
          setEnvelope(res.envelope ?? null);
          setPreviewErrors([]);
        } else {
          setEnvelope(null);
          setPreviewErrors(res.errors);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setEnvelope(null);
        setPreviewErrors([
          { phase: "python", message: err instanceof Error ? err.message : "Preview failed" },
        ]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [blocked, hasContent, isDraft, packageId, debouncedYaml, debouncedPython, debouncedSample, debouncedToolName, version]);

  const rawEnvelope = useMemo(() => {
    if (!envelope) return "";
    try {
      return JSON.stringify(
        { ...envelope, body: JSON.parse(envelope.body) },
        null, 2,
      );
    } catch {
      return JSON.stringify(envelope, null, 2);
    }
  }, [envelope]);

  const handleCopy = async () => {
    if (!rawEnvelope) return;
    try {
      await navigator.clipboard.writeText(rawEnvelope);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Silently fall through — older browsers / restricted contexts.
    }
  };

  const handlePin = async () => {
    if (!envelope || !onPin || pinState === "pinning") return;
    setPinState("pinning");
    setPinError(null);
    try {
      await onPin(envelope);
      setPinState("success");
      if (pinRevertTimer.current) clearTimeout(pinRevertTimer.current);
      pinRevertTimer.current = setTimeout(() => {
        setPinState("idle");
        pinRevertTimer.current = null;
      }, 3500);
    } catch (err) {
      setPinError(err instanceof Error ? err.message : "Pin failed");
      setPinState("error");
    }
  };

  const runFullCheck = async () => {
    if (!hasContent || blocked || checkRunning) return;
    setCheckRunning(true);
    setCheckError(null);
    try {
      const result = await checkWidgetAuthoring({
        yaml_template: draft.yaml_template,
        python_code: draft.python_code || null,
        sample_payload: samplePayload,
        tool_name: draft.tool_name || null,
        include_runtime: true,
        include_screenshot: true,
      });
      setCheckResult(result);
      setLastCheckSignature(currentCheckSignature);
    } catch (err) {
      setCheckError(err instanceof Error ? err.message : "Full check failed");
    } finally {
      setCheckRunning(false);
    }
  };

  const canPin = !!onPin && !!envelope && !pinDisabledReason && pinState !== "pinning";

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-3 py-2">
        <div className="flex rounded-md border border-surface-border overflow-hidden">
          <button
            onClick={() => setMode("rendered")}
            className={
              "px-2.5 py-1 text-[12px] font-medium transition-colors " +
              (mode === "rendered" ? "bg-accent text-white" : "bg-transparent text-text-muted hover:bg-surface-overlay")
            }
          >
            Rendered
          </button>
          <button
            onClick={() => setMode("raw")}
            className={
              "px-2.5 py-1 text-[12px] font-medium transition-colors " +
              (mode === "raw" ? "bg-accent text-white" : "bg-transparent text-text-muted hover:bg-surface-overlay")
            }
          >
            Raw
          </button>
        </div>

        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={() => setVersion((v) => v + 1)}
            disabled={blocked || !hasContent || loading}
            title="Re-run preview"
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text-muted text-[12px] font-medium px-2.5 py-1 hover:bg-surface-overlay disabled:opacity-50 transition-colors"
          >
            {loading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
            <span className="hidden sm:inline">Refresh</span>
          </button>
          <button
            onClick={handleCopy}
            disabled={!rawEnvelope}
            title="Copy envelope JSON"
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text-muted text-[12px] font-medium px-2.5 py-1 hover:bg-surface-overlay disabled:opacity-50 transition-colors"
          >
            {copied ? <Check size={11} className="text-success" /> : <ClipboardCopy size={11} />}
            <span className="hidden sm:inline">{copied ? "Copied" : "Copy"}</span>
          </button>
          {onPin && (
            <button
              onClick={handlePin}
              disabled={!canPin}
              title={pinDisabledReason ?? "Pin this preview to the dashboard as a static card"}
              className={
                "inline-flex items-center gap-1.5 rounded-md text-[12px] font-semibold px-2.5 py-1 transition-colors " +
                (pinState === "success"
                  ? "bg-success/15 text-success border border-success/40"
                  : "bg-accent text-white hover:opacity-90 disabled:opacity-50")
              }
            >
              {pinState === "pinning" ? (
                <Loader2 size={11} className="animate-spin" />
              ) : pinState === "success" ? (
                <Check size={11} />
              ) : (
                <Pin size={11} />
              )}
              {pinState === "success" ? "Pinned" : "Pin as card"}
            </button>
          )}
          <button
            onClick={runFullCheck}
            disabled={blocked || !hasContent || checkRunning}
            title="Run validation, preview, static health, and browser runtime smoke"
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text-muted text-[12px] font-semibold px-2.5 py-1 hover:bg-surface-overlay disabled:opacity-50 transition-colors"
          >
            {checkRunning ? <Loader2 size={11} className="animate-spin" /> : <Sparkles size={11} />}
            <span className="hidden sm:inline">Full Check</span>
          </button>
        </div>
      </div>

      {loading && (
        <div className="h-[2px] bg-accent/40 animate-pulse" />
      )}

      <div className="flex-1 overflow-auto p-4">
        {!hasContent && (
          <div className="rounded-lg border border-dashed border-surface-border p-10 text-center">
            <Sparkles size={20} className="mx-auto mb-2 text-text-dim" />
            <div className="text-[13px] text-text-muted font-semibold mb-1">Start typing a YAML template</div>
            <div className="text-[12px] text-text-dim max-w-sm mx-auto">
              Your widget will appear here as you type. Preview updates live — no need to save first.
            </div>
          </div>
        )}

        {hasContent && validationErrors.length > 0 && (
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-4">
            <div className="flex items-center gap-1.5 text-[13px] font-semibold text-danger mb-2">
              <AlertTriangle size={13} /> Fix errors to see preview
            </div>
            <ul className="text-[12px] text-danger space-y-1">
              {validationErrors.map((e, i) => (
                <li key={i} className="font-mono">
                  {e.line ? `Line ${e.line}: ` : ""}{e.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        {hasContent && validationErrors.length === 0 && previewErrors.length > 0 && (
          <div className="rounded-lg border border-danger/30 bg-danger/5 p-4">
            <div className="flex items-center gap-1.5 text-[13px] font-semibold text-danger mb-2">
              <AlertTriangle size={13} /> Preview error
            </div>
            <ul className="text-[12px] text-danger space-y-1">
              {previewErrors.map((e, i) => (
                <li key={i} className="font-mono">{e.message}</li>
              ))}
            </ul>
          </div>
        )}

        {pinError && pinState === "error" && (
          <div className="mb-3 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
            {pinError}
          </div>
        )}

        {(checkError || checkResult) && (
          <div
            data-testid="widget-authoring-full-check"
            className={
              "mb-3 rounded-lg border px-3 py-3 " +
              (checkResult?.readiness === "ready" && !checkStale
                ? "border-success/30 bg-success/5"
                : checkResult?.readiness === "blocked"
                  ? "border-danger/30 bg-danger/5"
                  : "border-warning/30 bg-warning/5")
            }
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[12px] font-semibold text-text">
                  Full check {checkStale ? "stale" : checkResult ? checkResult.readiness.replace(/_/g, " ") : "failed"}
                </div>
                <div className="mt-0.5 text-[11px] text-text-muted">
                  {checkError ?? checkResult?.summary}
                </div>
              </div>
              {checkResult?.artifacts?.screenshot?.data_url && (
                <img
                  src={checkResult.artifacts.screenshot.data_url}
                  alt="Runtime check screenshot"
                  className="h-20 w-32 rounded border border-surface-border object-cover"
                />
              )}
            </div>
            {checkResult && (
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                <div className="space-y-1">
                  {checkResult.phases.map((phase, idx) => (
                    <div key={`${phase.name}-${idx}`} className="flex items-start gap-2 text-[11px]">
                      <span className={
                        "mt-1 size-1.5 rounded-full " +
                        (phase.status === "healthy"
                          ? "bg-success"
                          : phase.status === "failing"
                            ? "bg-danger"
                            : phase.status === "warning"
                              ? "bg-warning"
                              : "bg-text-dim")
                      } />
                      <span className="min-w-0">
                        <span className="font-mono text-text-muted">{phase.name}</span>
                        <span className="text-text-dim"> - {phase.message}</span>
                      </span>
                    </div>
                  ))}
                </div>
                {checkResult.issues.length > 0 && (
                  <ul className="space-y-1 text-[11px] text-text-muted">
                    {checkResult.issues.slice(0, 5).map((issue, idx) => (
                      <li key={idx} className="font-mono">
                        {issue.line ? `Line ${issue.line}: ` : ""}
                        {issue.message}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        )}

        {hasContent && envelope && previewErrors.length === 0 && mode === "rendered" && (
          <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
            <RichToolResult
              envelope={adaptToToolResultEnvelope(envelope)}
              dispatcher={NOOP_DISPATCHER}
              t={t}
            />
          </div>
        )}

        {hasContent && envelope && previewErrors.length === 0 && mode === "raw" && (
          <pre className="rounded-lg border border-surface-border bg-surface-raised p-4 text-[12px] font-mono text-text overflow-auto">
            {rawEnvelope}
          </pre>
        )}
      </div>
    </div>
  );
}
