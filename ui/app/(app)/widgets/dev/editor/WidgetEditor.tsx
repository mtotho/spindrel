import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Play, Sparkles } from "lucide-react";

import {
  useCreateWidgetPackage,
  useUpdateWidgetPackage,
  useWidgetPackage,
  validateWidgetPackage,
  type PreviewEnvelope,
  type ValidationIssue,
  type WidgetPackage,
} from "@/src/api/hooks/useWidgetPackages";
import { useTools, executeTool, type ToolItem } from "@/src/api/hooks/useTools";
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useHashTab } from "@/src/hooks/useHashTab";
import { useDebouncedValue } from "@/src/hooks/useDebouncedValue";
import { ToolSelector, shortToolName } from "@/src/components/shared/ToolSelector";
import { useWidgetImportStore } from "@/src/stores/widgetImport";

import { WidgetPackageHeader } from "./WidgetPackageHeader";
import { EditorPane, type EditorTab } from "./EditorPane";
import { PreviewPane } from "./PreviewPane";
import { ToolArgsForm } from "../ToolArgsForm";

const EDITOR_TABS: readonly EditorTab[] = ["yaml", "python", "sample"] as const;

const BLANK_YAML = "template:\n  v: 1\n  components:\n    - type: status\n      text: Hello\n";
const BLANK_SAMPLE = "{}\n";

interface Draft {
  name: string;
  description: string;
  tool_name: string;
  yaml_template: string;
  python_code: string;
  sample_text: string;
}

interface PinPayload {
  envelope: PreviewEnvelope;
  draft: Draft;
  samplePayload: Record<string, unknown>;
}

interface Props {
  packageId?: string;
  initialToolName?: string;
  onPinEnvelope?: (payload: PinPayload) => Promise<void>;
  navigateBase?: string;
}

function pkgToDraft(pkg: WidgetPackage): Draft {
  return {
    name: pkg.name,
    description: pkg.description ?? "",
    tool_name: pkg.tool_name,
    yaml_template: pkg.yaml_template ?? "",
    python_code: pkg.python_code ?? "",
    sample_text: pkg.sample_payload ? JSON.stringify(pkg.sample_payload, null, 2) : "",
  };
}

function newDraft(toolName: string): Draft {
  return {
    name: toolName ? `${toolName} template` : "",
    description: "",
    tool_name: toolName,
    yaml_template: BLANK_YAML,
    python_code: "",
    sample_text: BLANK_SAMPLE,
  };
}

function hasMeaningfulSample(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed) return false;
  if (trimmed === "{}" || trimmed === "{}\n") return false;
  return true;
}

export function WidgetEditor({
  packageId,
  initialToolName = "",
  onPinEnvelope,
  navigateBase = "/widgets/dev",
}: Props) {
  const navigate = useNavigate();
  const t = useThemeTokens();
  const { width } = useWindowSize();
  const isWide = width >= 1024;
  const [activeTab, setActiveTab] = useHashTab<EditorTab>("yaml", EDITOR_TABS as unknown as EditorTab[]);

  const isNew = !packageId;

  const { data: pkg, isLoading } = useWidgetPackage(isNew ? undefined : packageId);
  const { data: tools } = useTools();

  const [draft, setDraft] = useState<Draft | null>(isNew ? newDraft(initialToolName) : null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationIssue[]>([]);
  const [validationWarnings, setValidationWarnings] = useState<ValidationIssue[]>([]);

  const createMut = useCreateWidgetPackage();
  const updateMut = useUpdateWidgetPackage(pkg?.id ?? "");

  // Accept a pending handoff from the Recent tab ("Import into Templates").
  // `consume()` self-clears, so a later refresh of this tab can't re-apply.
  // We also skip if the editor is not in new-draft mode (i.e. we're editing
  // a saved package) to avoid overwriting persisted state.
  const consumeImport = useWidgetImportStore((s) => s.consume);
  const [importBanner, setImportBanner] = useState<string | null>(null);
  useEffect(() => {
    if (!isNew) return;
    const pending = consumeImport();
    if (!pending) return;
    const prettySample =
      pending.samplePayload == null
        ? "{}\n"
        : JSON.stringify(pending.samplePayload, null, 2);
    setDraft((prev) => ({
      ...(prev ?? newDraft(pending.toolName)),
      tool_name: pending.toolName,
      sample_text: prettySample,
    }));
    setImportBanner(
      `Sample loaded from a recent ${pending.toolName} call — edit the YAML to shape the widget.`,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (isNew) {
      setDraft((prev) => prev ?? newDraft(initialToolName));
    } else if (pkg) {
      setDraft((prev) => (prev === null ? pkgToDraft(pkg) : prev));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isNew, pkg?.id]);

  useEffect(() => {
    if (!isNew && pkg) {
      setDraft(pkgToDraft(pkg));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pkg?.id]);

  const dirty = useMemo(() => {
    if (!draft) return false;
    if (isNew) return !!draft.tool_name.trim();
    if (!pkg) return false;
    const fromPkg = pkgToDraft(pkg);
    return (
      draft.name !== fromPkg.name ||
      draft.description !== fromPkg.description ||
      draft.yaml_template !== fromPkg.yaml_template ||
      draft.python_code !== fromPkg.python_code ||
      draft.sample_text !== fromPkg.sample_text
    );
  }, [draft, pkg, isNew]);

  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const debouncedYaml = useDebouncedValue(draft?.yaml_template ?? "", 400);
  const debouncedPython = useDebouncedValue(draft?.python_code ?? "", 400);
  useEffect(() => {
    if (!debouncedYaml) {
      setValidationErrors([]);
      setValidationWarnings([]);
      return;
    }
    let cancelled = false;
    validateWidgetPackage({
      yaml_template: debouncedYaml,
      python_code: debouncedPython || null,
    })
      .then((res) => {
        if (cancelled) return;
        setValidationErrors(res.errors);
        setValidationWarnings(res.warnings);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [debouncedYaml, debouncedPython]);

  const parsedSample = useMemo<Record<string, unknown> | null>(() => {
    if (!draft?.sample_text.trim()) return {};
    try {
      const v = JSON.parse(draft.sample_text);
      if (v && typeof v === "object" && !Array.isArray(v)) {
        return v as Record<string, unknown>;
      }
      return { value: v };
    } catch {
      return null;
    }
  }, [draft?.sample_text]);

  const sampleJsonError = !!draft && draft.sample_text.trim() !== "" && parsedSample === null;

  const canSave =
    dirty &&
    !saving &&
    validationErrors.length === 0 &&
    !sampleJsonError &&
    !!draft?.name.trim() &&
    !!draft?.tool_name.trim();

  const handleSave = useCallback(async () => {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      if (isNew) {
        const created = await createMut.mutateAsync({
          tool_name: draft.tool_name,
          name: draft.name,
          description: draft.description || null,
          yaml_template: draft.yaml_template,
          python_code: draft.python_code || null,
          sample_payload: parsedSample ?? null,
        });
        navigate(`${navigateBase}?id=${created.id}#templates`, { replace: true });
      } else {
        await updateMut.mutateAsync({
          name: draft.name,
          description: draft.description || null,
          yaml_template: draft.yaml_template,
          python_code: draft.python_code || null,
          sample_payload: parsedSample ?? null,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Save failed";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }, [draft, isNew, parsedSample, createMut, updateMut, navigate, navigateBase]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (canSave) handleSave();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [canSave, handleSave]);

  const handlePin = useMemo(() => {
    if (!onPinEnvelope) return undefined;
    return async (envelope: PreviewEnvelope) => {
      if (!draft) return;
      await onPinEnvelope({
        envelope,
        draft,
        samplePayload: parsedSample ?? {},
      });
    };
  }, [onPinEnvelope, draft, parsedSample]);

  const pinDisabledReason = !draft?.tool_name.trim()
    ? "Set a tool name before pinning"
    : null;

  // --- Sample capture flow ------------------------------------------------
  const [captureOpen, setCaptureOpen] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [captureArgs, setCaptureArgs] = useState<Record<string, unknown>>({});

  const selectedTool = useMemo<ToolItem | null>(() => {
    if (!draft?.tool_name) return null;
    return (tools ?? []).find((tool) => shortToolName(tool) === draft.tool_name) ?? null;
  }, [tools, draft?.tool_name]);

  const runCapture = async () => {
    if (!selectedTool || !draft) return;
    setCapturing(true);
    setCaptureError(null);
    try {
      const result = await executeTool(selectedTool.tool_name, captureArgs);
      if (result.error) {
        setCaptureError(result.error);
        return;
      }
      const pretty = typeof result.result === "string"
        ? result.result
        : JSON.stringify(result.result, null, 2);
      setDraft({ ...draft, sample_text: pretty });
      setActiveTab("sample");
      setCaptureOpen(false);
    } catch (err) {
      setCaptureError(err instanceof Error ? err.message : "Capture failed");
    } finally {
      setCapturing(false);
    }
  };

  if (!isNew && isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <Spinner color={t.accent} />
      </div>
    );
  }

  if (!draft) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <Spinner color={t.accent} />
      </div>
    );
  }

  const readOnly = !isNew && !!pkg?.is_readonly;
  const hasTool = !!draft.tool_name.trim();
  const sampleReady = hasMeaningfulSample(draft.sample_text);

  // ---------------------------------------------------------------------
  // Stage 1: pick a tool. Shown only on brand-new drafts with no tool set.
  // ---------------------------------------------------------------------
  if (isNew && !hasTool) {
    return (
      <div className="flex-1 flex items-center justify-center bg-surface overflow-auto p-6">
        <div className="w-full max-w-lg rounded-xl border border-surface-border bg-surface-raised p-8">
          <div className="flex items-center gap-2 text-accent mb-2">
            <Sparkles size={16} />
            <span className="text-[11px] font-semibold uppercase tracking-wider">New template</span>
          </div>
          <h2 className="text-[18px] font-semibold text-text mb-2">
            Pick a tool to template
          </h2>
          <p className="text-[13px] text-text-muted leading-relaxed mb-5">
            A widget template styles the output of one tool. Next you'll run the
            tool to capture a live sample, then write a YAML template that maps
            fields from that sample into an interactive widget.
          </p>
          <div className="space-y-1 mb-3">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">Tool</span>
            <ToolSelector
              value={draft.tool_name || null}
              tools={tools ?? []}
              onChange={(v) =>
                setDraft({
                  ...draft,
                  tool_name: v,
                  name: draft.name.trim() || `${v} template`,
                })
              }
              resolveValue={shortToolName}
              size="md"
              placeholder="Search local tools, integrations, MCP servers…"
            />
          </div>
          <p className="text-[11px] text-text-dim">
            Or <button
              type="button"
              onClick={() => navigate("/widgets/dev#library")}
              className="text-accent hover:underline bg-transparent border-none cursor-pointer p-0"
            >browse the library</button> to fork an existing template.
          </p>
        </div>
      </div>
    );
  }

  // ---------------------------------------------------------------------
  // Stage 2+: full editor with metadata strip, guided sample capture row,
  // and the editor/preview split.
  // ---------------------------------------------------------------------
  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      {saveError && (
        <div className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-[12px] text-danger">
          {saveError}
        </div>
      )}

      {importBanner && (
        <div className="flex items-center justify-between gap-3 border-b border-accent/30 bg-accent/10 px-4 py-2 text-[12px] text-accent">
          <span className="flex items-center gap-2">
            <Sparkles size={12} />
            {importBanner}
          </span>
          <button
            type="button"
            onClick={() => setImportBanner(null)}
            className="rounded px-2 py-0.5 text-[11px] font-medium text-accent/80 hover:bg-accent/20"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Metadata strip */}
      <div className="flex flex-wrap items-end gap-3 border-b border-surface-border px-4 py-3 bg-surface-raised">
        <label className="flex flex-col gap-1 min-w-[220px] flex-[2]">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">Name</span>
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            disabled={readOnly}
            placeholder="e.g. Weather forecast card"
            className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[14px] font-semibold text-text outline-none focus:border-accent disabled:opacity-70"
          />
        </label>
        <div className="flex flex-col gap-1 min-w-[220px] flex-1">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">Tool</span>
          {isNew ? (
            <ToolSelector
              value={draft.tool_name || null}
              tools={tools ?? []}
              onChange={(v) => setDraft({ ...draft, tool_name: v })}
              resolveValue={shortToolName}
              size="md"
            />
          ) : (
            <span className="rounded-md border border-transparent bg-surface-overlay/60 px-2.5 py-1.5 text-[13px] font-mono text-text-muted">
              {draft.tool_name}
            </span>
          )}
        </div>
        <label className="flex flex-col gap-1 min-w-[260px] flex-[2]">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">Description</span>
          <input
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            disabled={readOnly}
            placeholder="Shown in the library"
            className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent disabled:opacity-70"
          />
        </label>
        <div className="flex items-center gap-2 self-end">
          <WidgetPackageHeader
            pkg={pkg}
            draft={draft}
            dirty={dirty}
            saving={saving}
            canSave={!!canSave}
            onSave={handleSave}
            isNew={isNew}
          />
        </div>
      </div>

      {/* Stage-2 guide: no sample yet. */}
      {!sampleReady && hasTool && (
        <div className="border-b border-surface-border bg-accent/[0.05]">
          <div className="px-4 py-3 flex flex-wrap items-center gap-3">
            <Sparkles size={14} className="text-accent shrink-0" />
            <div className="flex-1 min-w-[240px]">
              <div className="text-[12px] font-semibold text-text">
                Capture a sample to template against
              </div>
              <div className="text-[11px] text-text-muted">
                Run <span className="font-mono text-text">{draft.tool_name}</span> to see its actual output, then write YAML that targets those fields.
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={() => {
                  setCaptureArgs({});
                  setCaptureError(null);
                  setCaptureOpen(true);
                }}
                disabled={!selectedTool}
                title={selectedTool ? "" : "Tool not found in the live index — paste a sample on the Sample tab."}
                className="inline-flex items-center gap-1.5 rounded-md bg-accent text-white text-[12px] font-semibold px-3 py-1.5 hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                <Play size={12} />
                Run tool to capture
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("sample")}
                className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text text-[12px] font-medium px-3 py-1.5 hover:bg-surface-overlay transition-colors"
              >
                Paste sample JSON
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Editor + preview split */}
      <div className={"flex flex-1 overflow-hidden " + (isWide ? "flex-row" : "flex-col")}>
        <div className="flex flex-col flex-1 min-h-0 border-b border-surface-border md:border-b-0 md:border-r">
          <EditorPane
            draft={draft}
            onChange={(partial) => setDraft({ ...draft, ...partial })}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
            validationErrors={validationErrors}
            validationWarnings={validationWarnings}
            sampleJsonError={sampleJsonError}
            readOnly={readOnly}
          />
        </div>
        <div className="flex flex-col flex-1 min-h-0">
          <PreviewPane
            packageId={pkg?.id}
            isNew={isNew}
            draft={{
              yaml_template: draft.yaml_template,
              python_code: draft.python_code,
              sample_text: draft.sample_text,
              tool_name: draft.tool_name,
            }}
            samplePayload={parsedSample ?? {}}
            validationErrors={validationErrors}
            onPin={handlePin}
            pinDisabledReason={pinDisabledReason}
          />
        </div>
      </div>

      {saving && (
        <div className="absolute top-4 right-4 inline-flex items-center gap-1.5 rounded-md bg-surface-raised px-3 py-1.5 text-[12px] text-text-muted shadow-lg">
          <Loader2 size={12} className="animate-spin" />
          Saving…
        </div>
      )}

      {captureOpen && selectedTool && (
        <CaptureSampleModal
          tool={selectedTool}
          args={captureArgs}
          onArgsChange={setCaptureArgs}
          running={capturing}
          error={captureError}
          onCancel={() => setCaptureOpen(false)}
          onRun={runCapture}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Capture modal — wraps ToolArgsForm + executeTool for the "Run tool to
// capture sample" flow. Result lands in draft.sample_text.
// ---------------------------------------------------------------------------

function CaptureSampleModal({
  tool, args, onArgsChange, running, error, onCancel, onRun,
}: {
  tool: ToolItem;
  args: Record<string, unknown>;
  onArgsChange: (next: Record<string, unknown>) => void;
  running: boolean;
  error: string | null;
  onCancel: () => void;
  onRun: () => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !running) onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel, running]);
  return (
    <>
      <div onClick={onCancel} className="fixed inset-0 bg-black/50 z-[1000]" />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[1001] w-[520px] max-w-[92vw] max-h-[80vh] bg-surface-raised border border-surface-border rounded-xl shadow-2xl flex flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-surface-border p-4">
          <div>
            <div className="text-[14px] font-semibold text-text">Capture sample</div>
            <div className="text-[11px] text-text-dim font-mono mt-0.5">{tool.tool_name}</div>
          </div>
          <button
            type="button"
            onClick={onCancel}
            disabled={running}
            className="text-text-dim hover:text-text text-[13px] bg-transparent border-none cursor-pointer disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <ToolArgsForm
            schema={tool.parameters}
            values={args}
            onChange={onArgsChange}
          />
          {error && (
            <div className="mt-3 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          )}
        </div>
        <div className="border-t border-surface-border p-4 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={running}
            className="inline-flex items-center gap-1.5 rounded-md border border-surface-border text-text text-[12px] font-medium px-3 py-1.5 hover:bg-surface-overlay disabled:opacity-50 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onRun}
            disabled={running}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent text-white text-[12px] font-semibold px-3 py-1.5 hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            {running ? "Running…" : "Run tool"}
          </button>
        </div>
      </div>
    </>
  );
}
