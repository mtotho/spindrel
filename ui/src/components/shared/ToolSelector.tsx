/**
 * ToolSelector — searchable, source-grouped tool picker used by task/widget editors.
 */
import { useMemo } from "react";
import { Wrench } from "lucide-react";

import type { ToolItem } from "@/src/api/hooks/useTools";
import { SelectDropdown, type SelectDropdownOption } from "./SelectDropdown";

/** "google_workspace" -> "Google Workspace", "homeassistant" -> "Home Assistant" */
export function humanizeSource(s: string): string {
  const SPECIAL: Record<string, string> = {
    homeassistant: "Home Assistant",
    bluebubbles: "Blue Bubbles",
    web_search: "Web Search",
  };
  if (SPECIAL[s]) return SPECIAL[s];
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Split on -, _, and camelCase boundaries -> lowercase tokens */
export function tokenize(s: string): string[] {
  return s
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[-_]/g, " ")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
}

/** Compute the source key for grouping: integration name, "mcp:{server}", or "core" */
export function toolSourceKey(t: ToolItem): string {
  if (t.source_integration) return t.source_integration;
  if (t.server_name) return `mcp:${t.server_name}`;
  return "core";
}

/** Human-readable label for a source key */
export function sourceLabel(key: string): string {
  if (key === "core") return "Core";
  if (key.startsWith("mcp:")) return `MCP: ${key.slice(4)}`;
  return humanizeSource(key);
}

/** Strip redundant integration prefix from tool name for display / bare matching */
export function shortToolName(tool: ToolItem): string {
  if (!tool.source_integration) return tool.tool_name;
  const prefix = tool.source_integration + "-";
  if (tool.tool_name.startsWith(prefix)) return tool.tool_name.slice(prefix.length);
  const prefixUnderscore = tool.source_integration + "_";
  if (tool.tool_name.startsWith(prefixUnderscore)) return tool.tool_name.slice(prefixUnderscore.length);
  return tool.tool_name;
}

interface ToolSelectorProps {
  value: string | null;
  tools: ToolItem[];
  onChange: (value: string, tool: ToolItem) => void;
  /** Function that maps a tool -> the value emitted / used for matching. */
  resolveValue?: (tool: ToolItem) => string;
  placeholder?: string;
  size?: "sm" | "md";
  disabled?: boolean;
}

interface ToolOption extends SelectDropdownOption {
  tool: ToolItem;
  resolvedValue: string;
}

export function ToolSelector({
  value,
  tools,
  onChange,
  resolveValue = (tool) => tool.tool_name,
  placeholder = "Select tool...",
  size = "sm",
  disabled = false,
}: ToolSelectorProps) {
  const options = useMemo<ToolOption[]>(() => {
    const sourceOrder = new Map<string, number>();
    const sourceCounts = new Map<string, number>();
    for (const tool of tools) {
      const source = toolSourceKey(tool);
      sourceCounts.set(source, (sourceCounts.get(source) ?? 0) + 1);
    }
    [...sourceCounts.entries()]
      .sort((a, b) => {
        if (a[0] === "core") return -1;
        if (b[0] === "core") return 1;
        return b[1] - a[1] || sourceLabel(a[0]).localeCompare(sourceLabel(b[0]));
      })
      .forEach(([source], index) => sourceOrder.set(source, index));

    return [...tools]
      .sort((a, b) => {
        const sourceDiff = (sourceOrder.get(toolSourceKey(a)) ?? 99) - (sourceOrder.get(toolSourceKey(b)) ?? 99);
        return sourceDiff || shortToolName(a).localeCompare(shortToolName(b));
      })
      .map((tool) => {
        const source = toolSourceKey(tool);
        const resolvedValue = resolveValue(tool);
        return {
          value: resolvedValue,
          label: resolvedValue,
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
          resolvedValue,
        };
      });
  }, [resolveValue, tools]);

  const selectedTool = tools.find((tool) => resolveValue(tool) === value);

  return (
    <SelectDropdown
      value={value}
      onChange={(_, option) => {
        const toolOption = option as ToolOption;
        onChange(toolOption.resolvedValue, toolOption.tool);
      }}
      options={options}
      placeholder={value || placeholder}
      disabled={disabled}
      searchable
      searchPlaceholder="Search tools..."
      emptyLabel="No tools found"
      popoverWidth="wide"
      size={size}
      leadingIcon={<Wrench size={size === "md" ? 13 : 12} className="shrink-0 text-text-dim" />}
      renderValue={() => (
        <span className="flex min-w-0 items-center gap-2">
          <span className={`min-w-0 flex-1 truncate font-mono ${value ? "text-text" : "font-sans text-text-dim"}`}>
            {selectedTool ? (size === "md" ? resolveValue(selectedTool) : selectedTool.tool_name) : (value || placeholder)}
          </span>
          {selectedTool?.source_integration && (
            <span className="shrink-0 rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-dim">
              {humanizeSource(selectedTool.source_integration)}
            </span>
          )}
        </span>
      )}
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
  );
}
