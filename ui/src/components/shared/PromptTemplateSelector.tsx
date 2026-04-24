import { useCallback, useMemo } from "react";
import { FileText } from "lucide-react";
import { usePromptTemplates } from "../../api/hooks/usePromptTemplates";
import type { PromptTemplate } from "../../types/api";
import { SelectDropdown, type SelectDropdownOption } from "./SelectDropdown";

interface Props {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (v: string) => void;
  workspaceId?: string;
}

interface PromptTemplateOption extends SelectDropdownOption {
  template: PromptTemplate;
}

export function PromptTemplateSelector({ textareaRef, value, onChange, workspaceId }: Props) {
  const { data: templates } = usePromptTemplates(workspaceId);

  const insertTemplate = useCallback(
    (template: PromptTemplate) => {
      const ta = textareaRef.current;
      const insertText = template.content;
      if (ta) {
        const start = ta.selectionStart ?? value.length;
        const end = ta.selectionEnd ?? value.length;
        const newValue = value.slice(0, start) + insertText + value.slice(end);
        onChange(newValue);
        // Restore cursor after insert
        requestAnimationFrame(() => {
          ta.focus();
          const pos = start + insertText.length;
          ta.setSelectionRange(pos, pos);
        });
      } else {
        onChange(value + insertText);
      }
    },
    [textareaRef, value, onChange]
  );

  const options = useMemo<PromptTemplateOption[]>(
    () =>
      (templates ?? []).map((tpl) => {
        const category = tpl.category || "Uncategorized";
        return {
          value: tpl.id,
          label: tpl.name,
          description: tpl.description || undefined,
          meta: tpl.workspace_id ? "workspace" : undefined,
          group: category,
          groupLabel: category,
          searchText: `${tpl.name} ${category} ${tpl.description ?? ""} ${tpl.content.slice(0, 160)}`,
          template: tpl,
        };
      }),
    [templates]
  );

  if (!templates || templates.length === 0) return null;

  return (
    <div className="inline-block min-w-[118px]">
      <SelectDropdown
        value={null}
        options={options}
        onChange={(_, option) => insertTemplate((option as PromptTemplateOption).template)}
        placeholder="Template"
        searchable
        searchPlaceholder="Search templates..."
        emptyLabel="No templates found"
        size="compact"
        popoverWidth={340}
        maxHeight={380}
        leadingIcon={<FileText size={12} className="text-text-dim" />}
        renderOption={(option) => {
          const tpl = (option as PromptTemplateOption).template;
          return (
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-[12px] font-semibold text-text">{tpl.name}</span>
                {tpl.workspace_id && (
                  <span className="shrink-0 rounded-sm bg-accent/[0.08] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-accent/80">
                    workspace
                  </span>
                )}
              </div>
              {tpl.description && (
                <div className="truncate pt-0.5 text-[11px] text-text-muted">{tpl.description}</div>
              )}
              <div className="truncate pt-1 font-mono text-[10px] text-text-dim">{tpl.content.slice(0, 80)}</div>
            </div>
          );
        }}
        triggerClassName="min-h-[26px] border-surface-border/70 bg-transparent text-text-muted hover:bg-surface-overlay/40"
      />
    </div>
  );
}
