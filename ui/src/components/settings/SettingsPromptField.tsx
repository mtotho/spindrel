import { useState, useEffect } from "react";
import { ChevronDown, Pencil, RotateCcw } from "lucide-react";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import type { SettingItem } from "@/src/api/hooks/useSettings";

interface Props {
  item: SettingItem;
  value: string;
  onChange: (v: string) => void;
}

const FIELD_TYPE_MAP: Record<string, string> = {
  MEMORY_FLUSH_DEFAULT_PROMPT: "memory_flush",
  MEMORY_HYGIENE_PROMPT: "memory_hygiene",
  SKILL_REVIEW_PROMPT: "skill_review",
  HEARTBEAT_DEFAULT_PROMPT: "heartbeat",
  HEARTBEAT_REPETITION_WARNING: "heartbeat_warning",
};

export function SettingsPromptField({ item, value, onChange }: Props) {
  const fieldType = FIELD_TYPE_MAP[item.key];
  const builtinDefault = item.builtin_default?.trim() ? item.builtin_default : "";
  const hasBuiltinDefault = !!builtinDefault;
  const hasCustomValue = value.trim().length > 0;

  const [editing, setEditing] = useState(!hasBuiltinDefault || hasCustomValue);
  const [showDefault, setShowDefault] = useState(false);

  useEffect(() => {
    if (hasBuiltinDefault && !value) setEditing(false);
  }, [value, hasBuiltinDefault]);

  // No built-in default — just show the editor
  if (!hasBuiltinDefault) {
    return (
      <div className="w-full">
        <PromptEditor
          value={value}
          onChange={onChange}
          placeholder="Enter prompt..."
          rows={8}
          fieldType={fieldType}
          generateContext={`Setting: ${item.label}. ${item.description}`}
        />
      </div>
    );
  }

  // Has built-in default — toggle between viewing default and editing custom
  return (
    <div className="flex w-full flex-col gap-2">
      {editing ? (
        <>
          <PromptEditor
            value={value}
            onChange={onChange}
            placeholder="Enter custom prompt..."
            rows={8}
            fieldType={fieldType}
            generateContext={`Setting: ${item.label}. ${item.description}`}
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => { onChange(""); setEditing(false); }}
              className="inline-flex min-h-[28px] items-center gap-1.5 rounded-md bg-transparent px-2 text-[11px] font-semibold text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text-muted"
            >
              <RotateCcw size={11} />
              Use built-in default
            </button>
          </div>
          <div className="overflow-hidden rounded-md bg-surface-raised/45">
            <button
              type="button"
              onClick={() => setShowDefault(!showDefault)}
              className="flex min-h-[32px] w-full items-center gap-1.5 px-2.5 text-left text-[11px] font-semibold text-text-dim transition-colors hover:bg-surface-overlay/50 hover:text-text-muted"
            >
              <ChevronDown
                size={11}
                className={`transition-transform duration-100 ${showDefault ? "" : "-rotate-90"}`}
              />
              View built-in default for reference
            </button>
            {showDefault && (
              <div className="px-2.5 pb-2.5">
                <pre className="max-h-[220px] overflow-auto whitespace-pre-wrap rounded bg-surface-overlay px-2.5 py-2 font-mono text-[11px] leading-relaxed text-text-muted">
                  {builtinDefault}
                </pre>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="overflow-hidden rounded-md bg-input">
          <div className="flex min-h-[38px] flex-wrap items-center justify-between gap-2 px-3 py-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim">
              Built-in default active
            </span>
            <button
              type="button"
              onClick={() => { onChange(builtinDefault); setEditing(true); }}
              className="inline-flex min-h-[28px] items-center gap-1.5 rounded-md bg-transparent px-2 text-[11px] font-semibold text-accent transition-colors hover:bg-accent/[0.08]"
            >
              <Pencil size={10} />
              Customize
            </button>
          </div>
          <textarea
            value={builtinDefault}
            readOnly
            rows={8}
            className="block max-h-[360px] min-h-[180px] w-full resize-y bg-transparent px-3 pb-3 pt-1 font-mono text-[16px] leading-[1.55] text-text-dim outline-none"
            aria-label={`${item.label} built-in default`}
          />
          <div className="flex justify-end px-3 pb-2 text-[11px] text-text-dim">
            {builtinDefault.length} chars {"\u00b7"} ~{Math.ceil(builtinDefault.length / 4)} tokens
          </div>
        </div>
      )}
    </div>
  );
}
