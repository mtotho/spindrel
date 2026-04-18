import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";

import {
  useCreateWidgetPackage,
  useUpdateWidgetPackage,
  useWidgetPackage,
  validateWidgetPackage,
  type PreviewEnvelope,
  type ValidationIssue,
  type WidgetPackage,
} from "@/src/api/hooks/useWidgetPackages";
import { useTools } from "@/src/api/hooks/useTools";
import { Spinner } from "@/src/components/shared/Spinner";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useHashTab } from "@/src/hooks/useHashTab";
import { useDebouncedValue } from "@/src/hooks/useDebouncedValue";

import { WidgetPackageHeader } from "./WidgetPackageHeader";
import { EditorPane, type EditorTab } from "./EditorPane";
import { PreviewPane } from "./PreviewPane";

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
  /** undefined → new draft mode. */
  packageId?: string;
  /** Prefill tool_name when creating a new draft (e.g. from ?tool=X). */
  initialToolName?: string;
  /**
   * Optional pin callback wired into the PreviewPane toolbar. When provided,
   * the rendered envelope + a snapshot of the draft are bubbled up so the
   * caller can write to the dashboard pins store.
   */
  onPinEnvelope?: (payload: PinPayload) => Promise<void>;
  /**
   * Route base used after a successful create. Defaults to `/widgets/dev`
   * (the Templates tab). Called as `${navigateBase}?id=${newId}#templates`.
   */
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
    name: toolName ? `${toolName} template` : "Untitled template",
    description: "",
    tool_name: toolName,
    yaml_template: BLANK_YAML,
    python_code: "",
    sample_text: BLANK_SAMPLE,
  };
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

  // Reset draft when switching between new / existing modes.
  useEffect(() => {
    if (isNew) {
      setDraft((prev) => prev ?? newDraft(initialToolName));
    } else if (pkg) {
      setDraft((prev) => (prev === null ? pkgToDraft(pkg) : prev));
    }
    // Only run when id transition or pkg load changes state shape.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isNew, pkg?.id]);

  // If packageId changes (e.g. after create redirect), reload draft from the new pkg.
  useEffect(() => {
    if (!isNew && pkg) {
      setDraft(pkgToDraft(pkg));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pkg?.id]);

  const dirty = useMemo(() => {
    if (!draft) return false;
    if (isNew) return true;
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
      // Preview supports any JSON; wrap non-objects so substitution still works.
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

  const toolOptions = (tools ?? [])
    .map((tool) => (tool.tool_name.includes("-") ? tool.tool_name.split("-").slice(1).join("-") : tool.tool_name))
    .filter((v, i, arr) => v && arr.indexOf(v) === i)
    .sort();

  const readOnly = !isNew && !!pkg?.is_readonly;

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      {saveError && (
        <div className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-[12px] text-danger">
          {saveError}
        </div>
      )}

      {/* Metadata strip — title + tool + description + save cluster on one line. */}
      <div className="flex flex-wrap items-end gap-3 border-b border-surface-border px-4 py-3 bg-surface-raised">
        <label className="flex flex-col gap-1 min-w-[220px] flex-[2]">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">Name</span>
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            disabled={readOnly}
            placeholder="e.g. Weather forecast card"
            className="rounded-md border border-surface-border bg-input-bg px-2.5 py-1.5 text-[14px] font-semibold text-text outline-none focus:border-accent disabled:opacity-70"
          />
        </label>
        <label className="flex flex-col gap-1 min-w-[160px]">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">Tool</span>
          {isNew ? (
            <input
              value={draft.tool_name}
              list="known-tools"
              onChange={(e) => setDraft({ ...draft, tool_name: e.target.value })}
              className="rounded-md border border-surface-border bg-input-bg px-2.5 py-1.5 text-[13px] font-mono text-text outline-none focus:border-accent"
              placeholder="list_tasks"
            />
          ) : (
            <span className="rounded-md border border-transparent bg-surface-overlay/60 px-2.5 py-1.5 text-[13px] font-mono text-text-muted">
              {draft.tool_name}
            </span>
          )}
          <datalist id="known-tools">
            {toolOptions.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </label>
        <label className="flex flex-col gap-1 min-w-[260px] flex-[3]">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">Description</span>
          <input
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            disabled={readOnly}
            placeholder="Shown in the library"
            className="rounded-md border border-surface-border bg-input-bg px-2.5 py-1.5 text-[13px] text-text-muted outline-none focus:border-accent disabled:opacity-70"
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

      {/* Editor + preview split */}
      <div
        className={
          "flex flex-1 overflow-hidden " +
          (isWide ? "flex-row" : "flex-col")
        }
      >
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
    </div>
  );
}
