import type { StepDef, ResponseSchema } from "@/src/api/hooks/useTasks";
import { JsonObjectEditor } from "../JsonObjectEditor";
import { MiniDropdown } from "./MiniDropdown";

const RESPONSE_SCHEMA_OPTIONS = [
  { value: "binary", label: "Approve / Reject" },
  { value: "multi_item", label: "Per-item approve/reject" },
];

const WIDGET_TEMPLATE_SKELETON = {
  kind: "approval_review",
  title: "Proposed changes",
  proposals_ref: "{{steps.analyze.result.proposals}}",
};

export function UserPromptFields({ step, readOnly, onChange }: {
  step: StepDef;
  readOnly?: boolean;
  onChange: (patch: Partial<StepDef>) => void;
}) {
  const schemaType = step.response_schema?.type ?? "binary";
  const itemsRef =
    step.response_schema && step.response_schema.type === "multi_item"
      ? step.response_schema.items_ref ?? ""
      : "";

  const setSchema = (next: ResponseSchema) => onChange({ response_schema: next });

  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">Title</label>
        <input
          type="text"
          value={step.title ?? ""}
          onChange={(e) => onChange({ title: e.target.value })}
          readOnly={readOnly}
          placeholder="Shown above the widget"
          className="bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs outline-none focus:border-accent/40 w-full"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-semibold uppercase tracking-wider text-text-dim">Response</label>
        <div className="flex flex-row items-center gap-2 flex-wrap">
          {readOnly ? (
            <span className="text-xs text-text-muted font-mono">{schemaType}</span>
          ) : (
            <MiniDropdown
              value={schemaType}
              options={RESPONSE_SCHEMA_OPTIONS}
              onChange={(v) => {
                if (v === "binary") setSchema({ type: "binary" });
                else setSchema({ type: "multi_item", items_ref: itemsRef });
              }}
            />
          )}
          {schemaType === "multi_item" && (
            <input
              type="text"
              value={itemsRef}
              onChange={(e) => setSchema({ type: "multi_item", items_ref: e.target.value })}
              readOnly={readOnly}
              placeholder="{{steps.analyze.result.proposals}}"
              className="flex-1 min-w-[200px] bg-input border border-surface-border rounded-md px-2.5 py-1.5 text-text text-xs font-mono outline-none focus:border-accent/40"
            />
          )}
        </div>
      </div>

      <JsonObjectEditor
        label="Widget template"
        hint="kind + args"
        value={step.widget_template ?? null}
        onChange={(next) => onChange({ widget_template: next })}
        readOnly={readOnly}
        schemaSkeleton={WIDGET_TEMPLATE_SKELETON}
        schemaLabel="Insert skeleton"
        placeholder='{"kind": "approval_review", ...}'
      />

      <JsonObjectEditor
        label="Widget args (optional)"
        hint="extra substitutions"
        value={step.widget_args ?? null}
        onChange={(next) => onChange({ widget_args: next })}
        readOnly={readOnly}
        placeholder="{}"
        minHeight={80}
        maxHeight={200}
      />
    </div>
  );
}
