/**
 * ChipPicker — searchable chip list for multi-select (skills, tools, etc.)
 * ToolMultiPicker — richer variant with source grouping + descriptions for tools.
 */
import { useMemo } from "react";
import type { ToolItem } from "@/src/api/hooks/useTools";
import { SelectDropdown, type SelectDropdownOption } from "../SelectDropdown";
import { shortToolName, sourceLabel, tokenize, toolSourceKey } from "../ToolSelector";

export function ChipPicker({ label, items, selected, onAdd, onRemove }: {
  label: string;
  items: { key: string; label: string; tag?: string }[];
  selected: string[];
  onAdd: (key: string) => void;
  onRemove: (key: string) => void;
}) {
  const selectedItems = items.filter((i) => selected.includes(i.key));
  const availableOptions = useMemo<SelectDropdownOption[]>(
    () =>
      items
        .filter((item) => !selected.includes(item.key))
        .map((item) => ({
          value: item.key,
          label: item.label,
          meta: item.tag,
          searchText: `${item.label} ${item.tag ?? ""}`,
        })),
    [items, selected],
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11px] text-text-dim font-semibold uppercase tracking-wider">
        {label}
        {selectedItems.length > 0 && (
          <span className="ml-1.5 text-accent font-bold">{selectedItems.length}</span>
        )}
      </div>
      <div className="flex flex-row gap-1.5 flex-wrap items-center min-h-[32px]">
        {selectedItems.map((item) => (
          <span
            key={item.key}
            className="inline-flex flex-row items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-accent/[0.08] text-accent border border-accent/20"
          >
            {item.label}
            <button
              onClick={() => onRemove(item.key)}
              className="bg-transparent border-none cursor-pointer text-sm text-accent p-0 leading-none opacity-60 hover:opacity-100"
            >
              &times;
            </button>
          </span>
        ))}
        <div className="w-[92px]">
          <SelectDropdown
            value={null}
            options={availableOptions}
            onChange={(key) => onAdd(key)}
            placeholder="+ Add"
            searchable
            searchPlaceholder={`Search ${label.toLowerCase()}...`}
            emptyLabel={items.length === 0 ? `No ${label.toLowerCase()} available` : "No matches"}
            disabled={availableOptions.length === 0}
            size="compact"
            popoverWidth={260}
            triggerClassName="min-h-[26px] rounded-full border-dashed bg-transparent text-[11px] font-semibold text-text-muted hover:border-accent/50 hover:bg-transparent hover:text-text-muted"
          />
        </div>
      </div>
    </div>
  );
}

export function ToolMultiPicker({ tools, selected, onAdd, onRemove }: {
  tools: ToolItem[];
  selected: string[];
  onAdd: (key: string) => void;
  onRemove: (key: string) => void;
}) {
  const available = useMemo(() => tools.filter((t) => !selected.includes(t.tool_key)), [tools, selected]);

  const selectedTools = tools.filter((t) => selected.includes(t.tool_key));
  const toolOptions = useMemo<ToolOption[]>(
    () =>
      available.map((tool) => {
        const source = toolSourceKey(tool);
        return {
          value: tool.tool_key,
          label: shortToolName(tool),
          description: tool.description ?? undefined,
          group: source,
          groupLabel: sourceLabel(source),
          searchText: [
            ...tokenize(tool.tool_name),
            ...tokenize(tool.description ?? ""),
            ...tokenize(tool.source_integration ?? ""),
            ...tokenize(tool.server_name ?? ""),
            ...tokenize(sourceLabel(source)),
          ].join(" "),
          tool,
        };
      }),
    [available],
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11px] text-text-dim font-semibold uppercase tracking-wider">
        Tools
        {selectedTools.length > 0 && (
          <span className="ml-1.5 text-accent font-bold">{selectedTools.length}</span>
        )}
      </div>
      <div className="flex flex-row gap-1.5 flex-wrap items-center min-h-[32px]">
        {selectedTools.map((tool) => (
          <span
            key={tool.tool_key}
            className="inline-flex flex-row items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-accent/[0.08] text-accent border border-accent/20"
            title={tool.description ?? undefined}
          >
            {tool.tool_name}
            {tool.source_integration && (
              <span className="text-[9px] text-accent/60">{sourceLabel(toolSourceKey(tool))}</span>
            )}
            <button
              onClick={() => onRemove(tool.tool_key)}
              className="bg-transparent border-none cursor-pointer text-sm text-accent p-0 leading-none opacity-60 hover:opacity-100"
            >
              &times;
            </button>
          </span>
        ))}
        <div className="w-[92px]">
          <SelectDropdown
            value={null}
            options={toolOptions}
            onChange={(key) => onAdd(key)}
            placeholder="+ Add"
            searchable
            searchPlaceholder="Search tools..."
            emptyLabel={available.length === 0 ? "All tools selected" : "No matches"}
            disabled={toolOptions.length === 0}
            size="compact"
            popoverWidth={340}
            triggerClassName="min-h-[26px] rounded-full border-dashed bg-transparent text-[11px] font-semibold text-text-muted hover:border-accent/50 hover:bg-transparent hover:text-text-muted"
            renderOption={(option, state) => {
              const tool = (option as ToolOption).tool;
              return (
                <span className="min-w-0 flex-1">
                  <span className={`flex min-w-0 items-center gap-2 text-[12px] font-medium ${state.selected ? "text-accent" : "text-text"}`}>
                    <span className="truncate">{shortToolName(tool)}</span>
                    {(tool.source_integration || tool.server_name) && (
                      <span className="shrink-0 rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-dim">
                        {sourceLabel(toolSourceKey(tool))}
                      </span>
                    )}
                  </span>
                  {tool.description && (
                    <span className="mt-0.5 block truncate text-[10px] text-text-dim">{tool.description}</span>
                  )}
                </span>
              );
            }}
          />
        </div>
      </div>
    </div>
  );
}

interface ToolOption extends SelectDropdownOption {
  tool: ToolItem;
}
