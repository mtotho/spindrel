import { AlertTriangle, CheckCircle2, Plus } from "lucide-react";

import { TabBar } from "@/src/components/shared/FormControls";
import { CodeEditor } from "@/src/components/shared/CodeEditor";
import { useThemeTokens } from "@/src/theme/tokens";
import type { ValidationIssue } from "@/src/api/hooks/useWidgetPackages";

export type EditorTab = "yaml" | "python" | "sample";

interface Draft {
  yaml_template: string;
  python_code: string;
  sample_text: string;
}

interface Props {
  draft: Draft;
  onChange: (next: Draft) => void;
  activeTab: EditorTab;
  setActiveTab: (k: EditorTab) => void;
  validationErrors: ValidationIssue[];
  validationWarnings: ValidationIssue[];
  sampleJsonError: boolean;
  readOnly: boolean;
}

function ValidationBar({
  errors, warnings, lineCount,
}: { errors: ValidationIssue[]; warnings: ValidationIssue[]; lineCount: number }) {
  if (errors.length) {
    const first = errors[0];
    return (
      <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-danger bg-danger/5 border-t border-danger/20">
        <AlertTriangle size={11} />
        <span className="font-medium">
          {first.line ? `Line ${first.line}: ` : ""}
          {first.message}
        </span>
        {errors.length > 1 && (
          <span className="text-text-dim">· {errors.length - 1} more</span>
        )}
      </div>
    );
  }
  if (warnings.length) {
    return (
      <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-warning bg-warning/5 border-t border-warning/20">
        <AlertTriangle size={11} />
        <span className="font-medium">{warnings[0].message}</span>
        {warnings.length > 1 && (
          <span className="text-text-dim">· {warnings.length - 1} more</span>
        )}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-text-dim border-t border-surface-border">
      <CheckCircle2 size={11} />
      Valid · {lineCount} line{lineCount === 1 ? "" : "s"}
    </div>
  );
}

export function EditorPane({
  draft, onChange, activeTab, setActiveTab,
  validationErrors, validationWarnings, sampleJsonError, readOnly,
}: Props) {
  const t = useThemeTokens();

  const yamlLines = draft.yaml_template.split("\n").length;

  const phaseErrors = (phase: "yaml" | "python") =>
    validationErrors.filter((e) => e.phase === phase || (phase === "yaml" && e.phase === "schema"));

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="flex items-center gap-3 px-3 py-2 border-b border-surface-border">
        <TabBar
          tabs={[
            { key: "yaml", label: `YAML${phaseErrors("yaml").length ? " ⚠" : ""}` },
            { key: "python", label: `Python${phaseErrors("python").length ? " ⚠" : draft.python_code.trim() ? "" : " +"}` },
            { key: "sample", label: `Sample${sampleJsonError ? " ⚠" : ""}` },
          ]}
          active={activeTab}
          onChange={(k) => setActiveTab(k as EditorTab)}
        />
      </div>

      {activeTab === "yaml" && (
        <>
          <div className="flex-1 min-h-0 flex">
            <CodeEditor
              content={draft.yaml_template}
              onChange={readOnly ? () => {} : (v) => onChange({ ...draft, yaml_template: v })}
              language="yaml"
              t={t}
            />
          </div>
          <ValidationBar
            errors={phaseErrors("yaml")}
            warnings={validationWarnings.filter((w) => w.phase !== "python")}
            lineCount={yamlLines}
          />
        </>
      )}

      {activeTab === "python" && (
        draft.python_code.trim() === "" && readOnly ? (
          <div className="flex-1 flex flex-col items-center justify-center p-10 text-center">
            <div className="text-[13px] font-semibold text-text-muted mb-1">No transform code</div>
            <div className="text-[12px] text-text-dim max-w-sm">
              This package relies only on the YAML template. Fork to add a Python transform.
            </div>
          </div>
        ) : draft.python_code.trim() === "" ? (
          <div className="flex-1 flex flex-col items-center justify-center p-10 text-center">
            <div className="text-[13px] font-semibold text-text-muted mb-1">No transform code</div>
            <div className="text-[12px] text-text-dim max-w-sm mb-4">
              Most templates work with <code className="font-mono text-accent">{"{{var | filter}}"}</code> alone.
              Add Python only if you need post-processing logic — for example, reshaping an API response before rendering.
            </div>
            <button
              onClick={() => onChange({
                ...draft,
                python_code: "def transform(data, components):\n    # data is the parsed tool result; components is the list of widget components.\n    return components\n",
              })}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent text-white text-[12px] font-semibold px-3 py-1.5 hover:opacity-90"
            >
              <Plus size={12} /> Add transform code
            </button>
          </div>
        ) : (
          <>
            <div className="px-3 py-2 text-[11px] text-text-dim border-b border-surface-border bg-surface-overlay/40">
              Define <code className="font-mono text-accent">{"def transform(data, components)"}</code> and reference it
              from YAML as <code className="font-mono text-accent">transform: self:transform</code>.
            </div>
            <div className="flex-1 min-h-0 flex">
              <CodeEditor
                content={draft.python_code}
                onChange={readOnly ? () => {} : (v) => onChange({ ...draft, python_code: v })}
                language="py"
                t={t}
              />
            </div>
            <ValidationBar
              errors={phaseErrors("python")}
              warnings={validationWarnings.filter((w) => w.phase === "python")}
              lineCount={draft.python_code.split("\n").length}
            />
          </>
        )
      )}

      {activeTab === "sample" && (
        <>
          <div className="px-3 py-2 text-[11px] text-text-dim border-b border-surface-border bg-surface-overlay/40">
            Sample tool result used for the live preview. Any JSON — keys become available as <code className="font-mono text-accent">{"{{var}}"}</code> in the template.
          </div>
          <div className="flex-1 min-h-0 flex">
            <CodeEditor
              content={draft.sample_text}
              onChange={readOnly ? () => {} : (v) => onChange({ ...draft, sample_text: v })}
              language="json"
              t={t}
            />
          </div>
          {sampleJsonError ? (
            <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-danger bg-danger/5 border-t border-danger/20">
              <AlertTriangle size={11} />
              Invalid JSON
            </div>
          ) : (
            <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-text-dim border-t border-surface-border">
              <CheckCircle2 size={11} />
              Valid JSON
            </div>
          )}
        </>
      )}
    </div>
  );
}
