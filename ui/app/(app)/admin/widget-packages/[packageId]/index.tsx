import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";

import {
  useCreateWidgetPackage,
  useUpdateWidgetPackage,
  useWidgetPackage,
  validateWidgetPackage,
  type ValidationIssue,
  type WidgetPackage,
} from "@/src/api/hooks/useWidgetPackages";
import { useTools } from "@/src/api/hooks/useTools";
import { PageHeader } from "@/src/components/layout/PageHeader";
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
  sample_text: string; // JSON text for the editor
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

export default function WidgetPackageEditor() {
  const { packageId } = useParams<{ packageId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const t = useThemeTokens();
  const { width } = useWindowSize();
  const isWide = width >= 1024;
  const [activeTab, setActiveTab] = useHashTab<EditorTab>("yaml", EDITOR_TABS as unknown as EditorTab[]);

  const isNew = !packageId || packageId === "new";
  const toolParam = searchParams.get("tool") ?? "";

  const { data: pkg, isLoading } = useWidgetPackage(isNew ? undefined : packageId);
  const { data: tools } = useTools();

  const [draft, setDraft] = useState<Draft | null>(isNew ? newDraft(toolParam) : null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [validationErrors, setValidationErrors] = useState<ValidationIssue[]>([]);
  const [validationWarnings, setValidationWarnings] = useState<ValidationIssue[]>([]);

  const createMut = useCreateWidgetPackage();
  const updateMut = useUpdateWidgetPackage(pkg?.id ?? "");

  // Hydrate draft when package loads.
  useEffect(() => {
    if (!isNew && pkg && draft === null) {
      setDraft(pkgToDraft(pkg));
    }
  }, [pkg, isNew, draft]);

  // Dirty detection — compare draft to stored body.
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

  // beforeunload guard
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // Debounced validation
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
      .catch(() => {
        // Network hiccup — don't block save UX.
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedYaml, debouncedPython]);

  const parsedSample = useMemo(() => {
    if (!draft?.sample_text.trim()) return {};
    try {
      return JSON.parse(draft.sample_text);
    } catch {
      return null;
    }
  }, [draft?.sample_text]);

  const sampleJsonError = draft && draft.sample_text.trim() !== "" && parsedSample === null;

  const canSave =
    dirty &&
    !saving &&
    validationErrors.length === 0 &&
    !sampleJsonError &&
    draft?.name.trim() &&
    draft?.tool_name.trim();

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
          sample_payload: parsedSample && typeof parsedSample === "object"
            ? (parsedSample as Record<string, unknown>)
            : null,
        });
        navigate(`/admin/widget-packages/${created.id}`, { replace: true });
      } else {
        await updateMut.mutateAsync({
          name: draft.name,
          description: draft.description || null,
          yaml_template: draft.yaml_template,
          python_code: draft.python_code || null,
          sample_payload: parsedSample && typeof parsedSample === "object"
            ? (parsedSample as Record<string, unknown>)
            : null,
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Save failed";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  }, [draft, isNew, parsedSample, createMut, updateMut, navigate]);

  // Cmd+S
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

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader
        variant="detail"
        backTo="/admin/tools?tab=library"
        parentLabel="Widget Library"
        title={isNew ? "New widget package" : draft.name || "Widget package"}
        subtitle={pkg ? `for tool: ${pkg.tool_name}` : toolParam ? `for tool: ${toolParam}` : undefined}
        right={
          <WidgetPackageHeader
            pkg={pkg}
            draft={draft}
            dirty={dirty}
            saving={saving}
            canSave={!!canSave}
            onSave={handleSave}
            isNew={isNew}
          />
        }
      />

      {saveError && (
        <div className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-[12px] text-danger">
          {saveError}
        </div>
      )}

      {/* Metadata strip */}
      <div className="flex flex-wrap gap-3 border-b border-surface-border px-4 py-3 bg-surface-raised">
        <label className="flex flex-col gap-1 min-w-[200px] flex-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">Name</span>
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            disabled={!isNew && pkg?.is_readonly}
            className="rounded-md border border-surface-border bg-input-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent"
          />
        </label>
        <label className="flex flex-col gap-1 min-w-[160px]">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">Tool name</span>
          {isNew ? (
            <input
              value={draft.tool_name}
              list="known-tools"
              onChange={(e) => setDraft({ ...draft, tool_name: e.target.value })}
              className="rounded-md border border-surface-border bg-input-bg px-2.5 py-1.5 text-[13px] font-mono text-text outline-none focus:border-accent"
              placeholder="e.g. list_tasks"
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
        <label className="flex flex-col gap-1 min-w-[260px] flex-[2]">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">Description</span>
          <input
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            disabled={!isNew && pkg?.is_readonly}
            className="rounded-md border border-surface-border bg-input-bg px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent"
          />
        </label>
      </div>

      {/* Editor + preview */}
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
            sampleJsonError={!!sampleJsonError}
            readOnly={!isNew && !!pkg?.is_readonly}
          />
        </div>
        <div className="flex flex-col flex-1 min-h-0">
          <PreviewPane
            packageId={pkg?.id}
            isNew={isNew}
            draft={draft}
            samplePayload={parsedSample ?? {}}
            validationErrors={validationErrors}
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
