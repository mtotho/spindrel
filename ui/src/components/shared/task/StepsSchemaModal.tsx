/**
 * StepsSchemaModal — pipeline authoring reference with selective copy.
 *
 * Shows schema + examples in the main area, tool groups as toggleable sections.
 * "Copy for AI" includes the schema plus only the tool groups you've toggled on.
 */
import { useState, useCallback, useMemo } from "react";
import { X, Copy, Check, HelpCircle, ChevronDown, ChevronRight } from "lucide-react";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";

// ---------------------------------------------------------------------------
// Static schema (mirrors skills/pipeline_authoring.md)
// ---------------------------------------------------------------------------

const SCHEMA_TEXT = `# Pipeline Steps — Authoring Reference

A pipeline is a Task with a \`steps\` array — an ordered list of step definitions that execute sequentially. Each step can be a shell command (\`exec\`), a direct tool call (\`tool\`), or an LLM conversation (\`agent\`).

Key principle: use exec and tool steps for deterministic work (free, no LLM tokens). Use agent steps for judgment and reasoning.

## Common Fields (all step types)

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| id | string | yes | — | Unique identifier. Used in templates and conditions |
| type | "exec" | "tool" | "agent" | yes | — | Determines execution engine |
| label | string | no | — | Human-readable name shown in UI |
| on_failure | "abort" | "continue" | no | "abort" | abort = stop pipeline. continue = proceed |
| when | object | no | — | Conditional execution. False → "skipped" |
| result_max_chars | number | no | 2000 | Max chars kept from output |

## Step Types

### exec — Shell Command
No LLM. Exit 0 = done, nonzero = failed.

Fields: prompt (string, the command), working_directory (string, optional)
Env vars from prior steps:
  $STEP_1_RESULT, $STEP_1_STATUS          — by 1-based index
  $STEP_CHECK_DISK_RESULT                  — by step ID (uppercased)

Auto-extracted JSON keys: if step 1 returns {"llm": "gpt-4o", "count": 30}:
  $STEP_1_llm = gpt-4o, $STEP_1_count = 30 (alongside $STEP_1_RESULT)

### tool — Direct Tool Call
No LLM. Calls a registered tool with arguments.

Fields: tool_name (string, exact name), tool_args (object, supports templates)

### agent — LLM Conversation
Spawns a child LLM task. Prior results auto-injected in preamble.

Fields: prompt (string), model (string, optional override), tools (string[], optional), carapaces (string[], optional)

## Templates

{{steps.1.result}} — result by 1-based index
{{steps.check_disk.result}} — result by step ID
{{steps.1.status}} — status by index ("done", "failed", "skipped")
{{steps.1.result.llm}} — extract "llm" key from step 1's JSON result
{{steps.1.result.config.model}} — dotted access into nested JSON

JSON field access: if a step returns valid JSON (dict), drill into it with dotted notation
after .result. If the key doesn't exist or result isn't JSON, template preserved as-is.

Shell values auto-escaped. Tool args support templates. Unresolved templates preserved as-is.

## Conditions (when)

{ "step": "id", "status": "done" }
{ "step": "id", "output_contains": "text" }
{ "step": "id", "output_not_contains": "text" }
{ "all": [ ...conditions ] }   — AND
{ "any": [ ...conditions ] }   — OR
{ "not": { condition } }       — NOT

## Examples

### Health Check
[
  { "id": "resources", "type": "exec", "prompt": "df -h / && free -h && uptime", "on_failure": "continue" },
  { "id": "docker", "type": "exec", "prompt": "docker ps --format 'table {{.Names}}\\t{{.Status}}'", "on_failure": "continue" },
  { "id": "analyze", "type": "agent", "prompt": "Review system health, flag concerns. Bullet points.", "model": "gpt-4o-mini" },
  { "id": "notify", "type": "tool", "tool_name": "slack-send_message", "tool_args": { "channel": "#ops", "text": "Health check done." }, "when": { "step": "analyze", "status": "done" } }
]

### Conditional Remediation
[
  { "id": "check", "type": "exec", "prompt": "df -h / | tail -1 | awk '{print $5}' | tr -d '%'" },
  { "id": "cleanup", "type": "exec", "prompt": "docker system prune -af 2>&1", "when": { "step": "check", "output_contains": "9" }, "on_failure": "continue" },
  { "id": "report", "type": "agent", "prompt": "Disk was {{steps.check.result}}%. Report cleanup actions." }
]

### Research & Report
[
  { "id": "search", "type": "tool", "tool_name": "web_search", "tool_args": { "query": "topic here" } },
  { "id": "analyze", "type": "agent", "prompt": "Identify top 3 findings and implications.", "tools": ["web_search"] },
  { "id": "format", "type": "agent", "prompt": "Format as executive briefing.", "model": "gpt-4o-mini" }
]

### Deployment with Rollback
[
  { "id": "test", "type": "exec", "prompt": "cd /opt/app && pytest tests/ -x -q 2>&1" },
  { "id": "build", "type": "exec", "prompt": "cd /opt/app && docker build -t myapp:latest . 2>&1 | tail -5" },
  { "id": "deploy", "type": "exec", "prompt": "cd /opt/app && docker compose up -d --build 2>&1", "when": { "step": "build", "status": "done" } },
  { "id": "verify", "type": "exec", "prompt": "sleep 10 && curl -sf http://localhost:8000/health || echo FAILED", "when": { "step": "deploy", "status": "done" } },
  { "id": "rollback", "type": "exec", "prompt": "cd /opt/app && docker compose down && docker compose up -d", "when": { "step": "verify", "output_contains": "FAILED" }, "on_failure": "continue" },
  { "id": "status", "type": "agent", "prompt": "Summarize deployment outcome.", "model": "gpt-4o-mini" }
]

## Tips
1. Start with exec, graduate to agent — shell is fast, free.
2. on_failure: "continue" for non-critical steps.
3. One job per agent step.
4. Use descriptive IDs — "check_disk" > "step_1".
5. Conditions > LLM judgment for branching.`;

// ---------------------------------------------------------------------------
// Tool group helpers
// ---------------------------------------------------------------------------

interface ToolGroup {
  key: string;
  label: string;
  tools: ToolItem[];
}

function buildToolGroups(tools: ToolItem[]): ToolGroup[] {
  const groups = new Map<string, ToolItem[]>();
  for (const t of tools) {
    const source = t.source_integration ?? (t.server_name ? `mcp:${t.server_name}` : "core");
    if (!groups.has(source)) groups.set(source, []);
    groups.get(source)!.push(t);
  }
  return [...groups.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([key, groupTools]) => ({
      key,
      label: key === "core"
        ? "Core"
        : key.startsWith("mcp:")
          ? `MCP: ${key.slice(4)}`
          : key.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()),
      tools: groupTools,
    }));
}

function toolGroupToText(group: ToolGroup): string {
  let text = `\n### ${group.label} (${group.tools.length} tools)\n\n`;
  for (const t of group.tools) {
    const desc = t.description ? ` — ${t.description}` : "";
    const params = t.parameters?.properties ?? t.schema_?.parameters?.properties;
    const paramList = params ? ` (${Object.keys(params).join(", ")})` : "";
    text += `- ${t.tool_name}${paramList}${desc}\n`;
  }
  return text;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StepsSchemaModal() {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [selectedGroups, setSelectedGroups] = useState<Set<string>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const { data: tools } = useTools();

  const toolGroups = useMemo(() => buildToolGroups(tools ?? []), [tools]);

  const toggleGroup = useCallback((key: string) => {
    setSelectedGroups(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const toggleExpanded = useCallback((key: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedGroups(new Set(toolGroups.map(g => g.key)));
  }, [toolGroups]);

  const selectNone = useCallback(() => {
    setSelectedGroups(new Set());
  }, []);

  const copyText = useMemo(() => {
    let text = SCHEMA_TEXT;
    if (selectedGroups.size > 0) {
      text += `\n\n## Available Tools\n`;
      for (const group of toolGroups) {
        if (selectedGroups.has(group.key)) {
          text += toolGroupToText(group);
        }
      }
    }
    return text;
  }, [selectedGroups, toolGroups]);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  }, [copyText]);

  const toolCount = selectedGroups.size > 0
    ? toolGroups.filter(g => selectedGroups.has(g.key)).reduce((n, g) => n + g.tools.length, 0)
    : 0;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="flex flex-row items-center gap-1 px-1.5 py-1 text-[11px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent transition-colors"
        title="View pipeline schema & available tools"
      >
        <HelpCircle size={13} />
        <span className="max-sm:hidden">Schema</span>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
        >
          <div className="bg-surface border border-surface-border rounded-xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col mx-4">
            {/* Header */}
            <div className="flex flex-row items-center justify-between px-5 py-3.5 border-b border-surface-border shrink-0">
              <div className="flex flex-col gap-0.5">
                <h3 className="text-sm font-semibold text-text m-0">Pipeline Authoring Reference</h3>
                <span className="text-[11px] text-text-dim">
                  Schema + examples{toolCount > 0 ? ` + ${toolCount} selected tools` : ""}
                </span>
              </div>
              <div className="flex flex-row items-center gap-2">
                <button
                  onClick={handleCopy}
                  className="flex flex-row items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-accent/10 text-accent border border-accent/30 rounded-lg cursor-pointer hover:bg-accent/20 transition-colors"
                >
                  {copied ? <Check size={13} /> : <Copy size={13} />}
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

            {/* Body — two-pane: schema left, tool picker right */}
            <div className="flex flex-row flex-1 min-h-0 overflow-hidden">
              {/* Schema pane */}
              <div className="flex-1 overflow-y-auto px-5 py-4 border-r border-surface-border min-w-0">
                <pre className="text-xs font-mono text-text-muted leading-relaxed whitespace-pre-wrap m-0">
                  {SCHEMA_TEXT}
                </pre>
              </div>

              {/* Tool picker pane */}
              <div className="w-[240px] shrink-0 flex flex-col overflow-hidden max-sm:hidden">
                <div className="flex flex-row items-center justify-between px-3 py-2.5 border-b border-surface-border shrink-0">
                  <span className="text-[11px] font-semibold text-text-dim uppercase tracking-wider">
                    Include Tools
                  </span>
                  <div className="flex flex-row items-center gap-1.5">
                    <button
                      onClick={selectAll}
                      className="text-[10px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent transition-colors"
                    >
                      All
                    </button>
                    <span className="text-text-dim/30 text-[10px]">|</span>
                    <button
                      onClick={selectNone}
                      className="text-[10px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent transition-colors"
                    >
                      None
                    </button>
                  </div>
                </div>
                <div className="flex-1 overflow-y-auto py-1">
                  {toolGroups.map((group) => {
                    const isSelected = selectedGroups.has(group.key);
                    const isExpanded = expandedGroups.has(group.key);
                    return (
                      <div key={group.key}>
                        <div className="flex flex-row items-center gap-1.5 px-3 py-1.5 hover:bg-surface-raised/50 transition-colors">
                          <button
                            onClick={() => toggleExpanded(group.key)}
                            className="p-0 bg-transparent border-none cursor-pointer text-text-dim hover:text-text shrink-0"
                          >
                            {isExpanded
                              ? <ChevronDown size={11} />
                              : <ChevronRight size={11} />
                            }
                          </button>
                          <label className="flex flex-row items-center gap-2 flex-1 min-w-0 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleGroup(group.key)}
                              className="accent-accent shrink-0 w-3.5 h-3.5 cursor-pointer"
                            />
                            <span className="text-xs text-text truncate">{group.label}</span>
                            <span className="text-[10px] text-text-dim ml-auto shrink-0">{group.tools.length}</span>
                          </label>
                        </div>
                        {isExpanded && (
                          <div className="pl-9 pr-3 pb-1">
                            {group.tools.slice(0, 20).map((t) => (
                              <div key={t.tool_key} className="text-[10px] text-text-dim py-0.5 truncate" title={t.description ?? t.tool_name}>
                                {t.tool_name}
                              </div>
                            ))}
                            {group.tools.length > 20 && (
                              <div className="text-[10px] text-text-dim/50 py-0.5">
                                +{group.tools.length - 20} more
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                  {toolGroups.length === 0 && (
                    <div className="px-3 py-4 text-[11px] text-text-dim text-center">
                      No tools registered
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
