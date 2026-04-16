/**
 * StepsSchemaModal — modal overlay showing the pipeline steps JSON schema
 * reference, dynamically augmented with available tools. Copy button lets
 * users paste the full context to AI for generation.
 */
import { useState, useCallback, useMemo } from "react";
import { X, Copy, Check, HelpCircle } from "lucide-react";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";

// ---------------------------------------------------------------------------
// Static schema sections
// ---------------------------------------------------------------------------

const SCHEMA_HEADER = `# Pipeline Steps JSON Schema

An array of step objects. Each step runs sequentially; prior results are available via templating.

## Step Object

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string | yes | Unique identifier, e.g. "step_1", "fetch_data" |
| type | "exec" | "tool" | "agent" | yes | Step type (see below) |
| label | string | no | Human-readable name |
| on_failure | "abort" | "continue" | no | What to do if this step fails (default: "abort") |
| when | object | no | Conditional execution (see Conditions) |

### Type: "exec" (Shell command)

| Field | Type | Description |
|-------|------|-------------|
| prompt | string | The shell command to execute |
| working_directory | string | Working directory for the command |
| result_max_chars | number | Max chars to keep from output |

### Type: "tool" (Call a registered tool)

| Field | Type | Description |
|-------|------|-------------|
| tool_name | string | Name of the tool to invoke |
| tool_args | object | Arguments to pass to the tool |

### Type: "agent" (LLM prompt)

| Field | Type | Description |
|-------|------|-------------|
| prompt | string | The prompt to send to the LLM. Prior step results are auto-injected. |
| model | string | Model override (e.g. "gpt-4o", "claude-sonnet-4-20250514") |
| tools | string[] | Tool names available to the agent |
| carapaces | string[] | Capability/skill IDs to activate |

## Conditions (when)

Skip a step unless a condition is met. Refers to the previous step.

{ "step": "step_1", "output_contains": "SUCCESS" }
{ "step": "step_1", "output_not_contains": "ERROR" }
{ "step": "step_1", "status": "done" }

## Templating

In prompts: {{steps.1.result}} or {{steps.step_id.result}}
In shell commands: $STEP_1_RESULT, $STEP_1_STATUS`;

const EXAMPLE_SECTION = `
## Example

[
  {
    "id": "step_1",
    "type": "exec",
    "label": "List files",
    "prompt": "ls -la /tmp",
    "on_failure": "abort"
  },
  {
    "id": "step_2",
    "type": "agent",
    "label": "Summarize",
    "prompt": "Summarize this directory listing: {{steps.1.result}}",
    "on_failure": "continue"
  },
  {
    "id": "step_3",
    "type": "tool",
    "label": "Send notification",
    "tool_name": "slack-send_message",
    "tool_args": {
      "channel": "#updates",
      "text": "Summary complete"
    },
    "when": { "step": "step_2", "status": "done" }
  }
]`;

// ---------------------------------------------------------------------------
// Dynamic tool catalog builder
// ---------------------------------------------------------------------------

function buildToolCatalog(tools: ToolItem[]): string {
  if (tools.length === 0) return "";

  // Group by source
  const groups = new Map<string, ToolItem[]>();
  for (const t of tools) {
    const source = t.source_integration ?? (t.server_name ? `mcp:${t.server_name}` : "core");
    if (!groups.has(source)) groups.set(source, []);
    groups.get(source)!.push(t);
  }

  let text = "\n\n## Available Tools\n\n";
  text += `${tools.length} tools registered. Use exact tool_name values in tool steps.\n`;

  for (const [source, groupTools] of [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const label = source === "core" ? "Core" : source.startsWith("mcp:") ? `MCP: ${source.slice(4)}` : source.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    text += `\n### ${label}\n\n`;
    for (const t of groupTools.slice(0, 30)) {
      const desc = t.description ? ` — ${t.description}` : "";
      // Show parameter names if available
      const params = t.parameters?.properties ?? t.schema_?.parameters?.properties;
      const paramList = params ? ` (${Object.keys(params).join(", ")})` : "";
      text += `- \`${t.tool_name}\`${paramList}${desc}\n`;
    }
    if (groupTools.length > 30) {
      text += `- ... and ${groupTools.length - 30} more\n`;
    }
  }

  return text;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StepsSchemaModal() {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const { data: tools } = useTools();

  const fullText = useMemo(() => {
    const toolCatalog = buildToolCatalog(tools ?? []);
    return SCHEMA_HEADER + toolCatalog + EXAMPLE_SECTION;
  }, [tools]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(fullText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  }, [fullText]);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex flex-row items-center gap-1 px-1.5 py-1 text-[11px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent transition-colors"
        title="View steps JSON schema & available tools"
      >
        <HelpCircle size={13} />
        <span className="max-sm:hidden">Schema</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
        >
          <div className="bg-surface border border-surface-border rounded-xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col mx-4">
            {/* Header */}
            <div className="flex flex-row items-center justify-between px-5 py-3.5 border-b border-surface-border shrink-0">
              <div className="flex flex-col gap-0.5">
                <h3 className="text-sm font-semibold text-text m-0">Pipeline Steps Schema</h3>
                <span className="text-[11px] text-text-dim">
                  Copy and paste to AI to generate pipeline JSON
                </span>
              </div>
              <div className="flex flex-row items-center gap-2">
                <button
                  onClick={handleCopy}
                  className="flex flex-row items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-text-dim bg-surface-raised border border-surface-border rounded-lg cursor-pointer hover:text-text hover:border-accent/40 transition-colors"
                >
                  {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                  {copied ? "Copied!" : "Copy for AI"}
                </button>
                <button
                  onClick={() => setOpen(false)}
                  className="p-1.5 text-text-dim bg-transparent border-none cursor-pointer hover:text-text rounded-md hover:bg-surface-raised transition-colors"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              <pre className="text-xs font-mono text-text-muted leading-relaxed whitespace-pre-wrap m-0">
                {fullText}
              </pre>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
