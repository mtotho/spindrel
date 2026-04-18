import { AlertTriangle, Check, ClipboardCopy, Loader2, Pin, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  previewWidgetInline,
  previewWidgetPackage,
  type PreviewEnvelope,
  type ValidationIssue,
} from "@/src/api/hooks/useWidgetPackages";
import {
  ComponentRenderer,
  WidgetActionContext,
  type WidgetActionDispatcher,
} from "@/src/components/chat/renderers/ComponentRenderer";
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
  const pinRevertTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const debouncedYaml = useDebouncedValue(draft.yaml_template, 500);
  const debouncedPython = useDebouncedValue(draft.python_code, 500);
  const debouncedSample = useDebouncedValue(samplePayload, 500);
  const debouncedToolName = useDebouncedValue(draft.tool_name ?? "", 500);

  const isDraft = isNew || !packageId;
  const blocked = validationErrors.length > 0;
  const hasContent = debouncedYaml.trim().length > 0;

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

        {hasContent && envelope && previewErrors.length === 0 && mode === "rendered" && (
          <div className="rounded-lg border border-surface-border bg-surface-raised p-5">
            <WidgetActionContext.Provider value={NOOP_DISPATCHER}>
              <ComponentRenderer body={envelope.body} t={t} />
            </WidgetActionContext.Provider>
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
