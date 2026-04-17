import { AlertTriangle, RefreshCw, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
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
}

interface Props {
  packageId: string | undefined;
  isNew: boolean;
  draft: Draft;
  samplePayload: Record<string, unknown>;
  validationErrors: ValidationIssue[];
}

type ViewMode = "rendered" | "raw";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => {
    return { envelope: null, apiResponse: null };
  },
};

export function PreviewPane({
  packageId, isNew, draft, samplePayload, validationErrors,
}: Props) {
  const t = useThemeTokens();
  const [mode, setMode] = useState<ViewMode>("rendered");
  const [envelope, setEnvelope] = useState<PreviewEnvelope | null>(null);
  const [previewErrors, setPreviewErrors] = useState<ValidationIssue[]>([]);
  const [loading, setLoading] = useState(false);
  const [version, setVersion] = useState(0);

  const debouncedYaml = useDebouncedValue(draft.yaml_template, 500);
  const debouncedPython = useDebouncedValue(draft.python_code, 500);
  const debouncedSample = useDebouncedValue(samplePayload, 500);

  const blocked = validationErrors.length > 0 || isNew || !packageId;

  useEffect(() => {
    if (blocked) {
      setEnvelope(null);
      setPreviewErrors([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    previewWidgetPackage(packageId!, {
      yaml_template: debouncedYaml,
      python_code: debouncedPython || null,
      sample_payload: debouncedSample as Record<string, unknown>,
    })
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
  }, [blocked, packageId, debouncedYaml, debouncedPython, debouncedSample, version]);

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

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-surface">
      <div className="flex items-center gap-2 border-b border-surface-border px-3 py-2">
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
            Raw envelope
          </button>
        </div>

        <button
          onClick={() => setVersion((v) => v + 1)}
          disabled={blocked || loading}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text-muted text-[12px] font-medium px-2.5 py-1 hover:bg-surface-overlay disabled:opacity-50 transition-colors"
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
          Refresh
        </button>
      </div>

      {loading && (
        <div className="h-[2px] bg-accent/40 animate-pulse" />
      )}

      <div className="flex-1 overflow-auto p-4">
        {isNew && (
          <div className="rounded-lg border border-dashed border-surface-border p-6 text-center text-[12px] text-text-dim">
            Save the package first to enable live preview.
          </div>
        )}

        {!isNew && validationErrors.length > 0 && (
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

        {!isNew && validationErrors.length === 0 && previewErrors.length > 0 && (
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

        {!isNew && envelope && previewErrors.length === 0 && mode === "rendered" && (
          <div className="rounded-lg border border-surface-border bg-surface-raised p-4">
            <WidgetActionContext.Provider value={NOOP_DISPATCHER}>
              <ComponentRenderer body={envelope.body} t={t} />
            </WidgetActionContext.Provider>
          </div>
        )}

        {!isNew && envelope && previewErrors.length === 0 && mode === "raw" && (
          <pre className="rounded-lg border border-surface-border bg-surface-raised p-4 text-[12px] font-mono text-text overflow-auto">
            {rawEnvelope}
          </pre>
        )}
      </div>
    </div>
  );
}
