/**
 * StepsSchemaModal — pipeline authoring reference with selective copy.
 *
 * Left pane: schema + examples. Right pane: toggleable sections (models, tiers,
 * tool groups) that get appended to the copy text when checked.
 */
import { useState, useCallback, useMemo } from "react";
import { X, Copy, Check, HelpCircle, ChevronDown, ChevronRight } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
import { useModelGroups } from "@/src/api/hooks/useModels";
import { apiFetch } from "@/src/api/client";
import type { ModelGroup } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Static schema (mirrors skills/pipeline_authoring.md)
// ---------------------------------------------------------------------------

const SCHEMA_TEXT = `# Pipeline Steps — Authoring Reference

A pipeline is a Task with a \`steps\` array — an ordered list of step definitions that execute sequentially. Each step can be a shell command (\`exec\`), a machine command (\`machine_inspect\` / \`machine_exec\`), a direct tool call (\`tool\`), or an LLM conversation (\`agent\`).

Key principle: use exec and tool steps for deterministic work (free, no LLM tokens). Use agent steps for judgment and reasoning.

## Common Fields (all step types)

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| id | string | yes | — | Unique identifier. Used in templates and conditions |
| type | "exec" | "machine_inspect" | "machine_exec" | "tool" | "agent" | "user_prompt" | "foreach" | yes | — | Determines execution engine |
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

### machine_inspect / machine_exec — Task-Granted Machine Command
No LLM. Requires a Machine target grant on the task definition.

Fields: command (string), working_directory (string, optional for machine_exec)
machine_inspect uses the readonly inspect command allowlist. machine_exec allows shell execution.

### tool — Direct Tool Call
No LLM. Calls a registered tool with arguments.

Fields: tool_name (string, exact name), tool_args (object, supports templates)

### agent — LLM Conversation
Spawns a child LLM task. Prior results auto-injected in preamble.

Fields: prompt (string), model (string, optional override), tools (string[], optional)

### user_prompt — Pause for Human Approval
Pauses the pipeline and emits a widget into the channel. Resumes when the user resolves it.

Fields:
  title (string, optional)                            — shown above the widget
  widget_template (object)                            — { kind: "...", ...args }; supports {{steps.*}}, {{params.*}}, {{item.*}}
  widget_args (object, optional)                      — extra substitution context
  response_schema (object, required)                  — one of:
    { "type": "binary" }                              — response is { decision: "approve"|"reject" }
    { "type": "multi_item", "items_ref": "..." }      — response is { "<item_id>": "approve"|"reject", ... }

Downstream steps read the response via {{steps.<id>.result.decision}} or key-indexed per-item access.

### foreach — Iterate Over a List
Runs a sub-sequence of steps once per item of a prior-step list result. Sequential in v1.

Fields:
  over (string, required)                             — {{steps.*}} / {{params.*}} expression resolving to a list
  on_failure ("abort"|"continue")                     — default "abort" on the outer loop
  do (step[])                                         — v1 supports only tool sub-steps

Per-iteration bindings: {{item}}, {{item.field}}, {{item_index}}, {{item_count}}. Sub-step when: can gate on
outer-pipeline steps.

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

### Approval Gate + Batch Apply (user_prompt + foreach)
[
  { "id": "analyze", "type": "agent", "prompt": "Return JSON: { \\"proposals\\": [{ \\"id\\": \\"...\\", \\"target_path\\": \\"...\\", \\"patch_body\\": {...} }] }" },
  { "id": "review", "type": "user_prompt",
    "title": "Review proposed changes",
    "widget_template": { "kind": "approval_review", "proposals_ref": "{{steps.analyze.result.proposals}}" },
    "response_schema": { "type": "multi_item", "items_ref": "{{steps.analyze.result.proposals}}" } },
  { "id": "apply", "type": "foreach",
    "over": "{{steps.analyze.result.proposals}}",
    "on_failure": "continue",
    "do": [
      { "id": "apply_one", "type": "tool", "tool_name": "call_api",
        "when": { "step": "review", "output_contains": "approve" },
        "tool_args": { "method": "PATCH", "path": "{{item.target_path}}", "body": "{{item.patch_body}}" } }
    ] }
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
// Tier definitions (matches ModelTiersSection)
// ---------------------------------------------------------------------------

const TIER_ORDER = ["free", "fast", "standard", "capable", "frontier"] as const;
type TierName = (typeof TIER_ORDER)[number];

const TIER_LABELS: Record<TierName, { label: string; hint: string }> = {
  free: { label: "Free", hint: "Zero-cost / rate-limited" },
  fast: { label: "Fast", hint: "Trivial extraction, scanning" },
  standard: { label: "Standard", hint: "Research, code review" },
  capable: { label: "Capable", hint: "Multi-step reasoning" },
  frontier: { label: "Frontier", hint: "Complex / high-stakes" },
};

interface TierEntry { model: string; provider_id?: string | null }
type TiersMap = Partial<Record<TierName, TierEntry>>;

function useGlobalModelTiers() {
  return useQuery({
    queryKey: ["global-model-tiers"],
    queryFn: () => apiFetch<{ tiers: TiersMap }>("/api/v1/admin/global-model-tiers"),
    staleTime: 5 * 60 * 1000,
  });
}

// ---------------------------------------------------------------------------
// Text builders for copy
// ---------------------------------------------------------------------------

function buildModelsText(modelGroups: ModelGroup[]): string {
  if (modelGroups.length === 0) return "";
  let text = "\n\n## Available LLM Models\n\nUse exact model IDs in agent step `model` field.\n";
  for (const group of modelGroups) {
    text += `\n### ${group.provider_name}\n\n`;
    for (const m of group.models) {
      const tokens = m.max_tokens ? ` (${(m.max_tokens / 1000).toFixed(0)}k ctx)` : "";
      text += `- ${m.id}${tokens}\n`;
    }
  }
  return text;
}

function buildTiersText(tiers: TiersMap): string {
  let text = "\n\n## Model Tiers\n\nInstead of hardcoding a model, you can select a tier appropriate to the step's complexity.\n\n";
  text += "| Tier | Use Case | Currently Mapped To |\n";
  text += "|------|----------|---------------------|\n";
  for (const tier of TIER_ORDER) {
    const meta = TIER_LABELS[tier];
    const entry = tiers[tier];
    const model = entry?.model ?? "(not configured)";
    text += `| ${meta.label} | ${meta.hint} | ${model} |\n`;
  }
  text += "\nWhen authoring pipelines, consider which tier fits each agent step:\n";
  text += "- Summarization, formatting → fast or standard\n";
  text += "- Analysis, reasoning → capable\n";
  text += "- Complex multi-tool orchestration → frontier\n";
  return text;
}

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
// Sidebar section keys
// ---------------------------------------------------------------------------

// Special keys for non-tool sections
const KEY_MODELS = "__models__";
const KEY_TIERS = "__tiers__";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StepsSchemaModal() {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { data: tools } = useTools();
  const { data: modelGroups } = useModelGroups();
  const { data: tiersData } = useGlobalModelTiers();

  const toolGroups = useMemo(() => buildToolGroups(tools ?? []), [tools]);
  const tiers = tiersData?.tiers ?? {};

  const toggle = useCallback((key: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  const toggleExp = useCallback((key: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  const allKeys = useMemo(() => {
    const keys = [KEY_MODELS, KEY_TIERS, ...toolGroups.map(g => g.key)];
    return keys;
  }, [toolGroups]);

  const selectAll = useCallback(() => setSelected(new Set(allKeys)), [allKeys]);
  const selectNone = useCallback(() => setSelected(new Set()), []);

  // Build the copy text
  const copyText = useMemo(() => {
    let text = SCHEMA_TEXT;
    if (selected.has(KEY_MODELS) && modelGroups) {
      text += buildModelsText(modelGroups);
    }
    if (selected.has(KEY_TIERS)) {
      text += buildTiersText(tiers);
    }
    const selectedToolGroups = toolGroups.filter(g => selected.has(g.key));
    if (selectedToolGroups.length > 0) {
      text += "\n\n## Available Tools\n";
      for (const group of selectedToolGroups) {
        text += toolGroupToText(group);
      }
    }
    return text;
  }, [selected, toolGroups, modelGroups, tiers]);

  const handleCopy = useCallback(() => {
    const el = document.createElement("textarea");
    el.value = copyText;
    el.style.position = "fixed";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.select();
    document.execCommand("copy");
    document.body.removeChild(el);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [copyText]);

  // Count selected extras
  const extraCount = useMemo(() => {
    let count = 0;
    if (selected.has(KEY_MODELS)) count += modelGroups?.reduce((n, g) => n + g.models.length, 0) ?? 0;
    if (selected.has(KEY_TIERS)) count += TIER_ORDER.length;
    count += toolGroups.filter(g => selected.has(g.key)).reduce((n, g) => n + g.tools.length, 0);
    return count;
  }, [selected, toolGroups, modelGroups]);

  const modelCount = modelGroups?.reduce((n, g) => n + g.models.length, 0) ?? 0;

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
          className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60"
          onClick={(e) => { if (e.target === e.currentTarget) setOpen(false); }}
        >
          <div className="bg-surface border border-surface-border rounded-lg w-full max-w-3xl max-h-[85vh] flex flex-col mx-4">
            {/* Header */}
            <div className="flex flex-row items-center justify-between px-5 py-3.5 border-b border-surface-border shrink-0">
              <div className="flex flex-col gap-0.5">
                <h3 className="text-sm font-semibold text-text m-0">Pipeline Authoring Reference</h3>
                <span className="text-[11px] text-text-dim">
                  Schema + examples{extraCount > 0 ? ` + ${extraCount} items selected` : ""}
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

            {/* Body — two-pane */}
            <div className="flex flex-row flex-1 min-h-0 overflow-hidden">
              {/* Schema pane */}
              <div className="flex-1 overflow-y-auto px-5 py-4 border-r border-surface-border min-w-0">
                <pre className="text-xs font-mono text-text-muted leading-relaxed whitespace-pre-wrap m-0">
                  {SCHEMA_TEXT}
                </pre>
              </div>

              {/* Include pane */}
              <div className="w-[240px] shrink-0 flex flex-col overflow-hidden max-sm:hidden">
                <div className="flex flex-row items-center justify-between px-3 py-2.5 border-b border-surface-border shrink-0">
                  <span className="text-[11px] font-semibold text-text-dim uppercase tracking-wider">
                    Include in Copy
                  </span>
                  <div className="flex flex-row items-center gap-1.5">
                    <button onClick={selectAll} className="text-[10px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent transition-colors">All</button>
                    <span className="text-text-dim/30 text-[10px]">|</span>
                    <button onClick={selectNone} className="text-[10px] text-text-dim bg-transparent border-none cursor-pointer hover:text-accent transition-colors">None</button>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto py-1">
                  {/* --- Models section --- */}
                  <SectionHeader label="Models" />
                  <CheckRow
                    label="Available LLMs"
                    count={modelCount}
                    checked={selected.has(KEY_MODELS)}
                    onToggle={() => toggle(KEY_MODELS)}
                    expanded={expanded.has(KEY_MODELS)}
                    onExpand={() => toggleExp(KEY_MODELS)}
                  />
                  {expanded.has(KEY_MODELS) && modelGroups && (
                    <div className="pl-9 pr-3 pb-1">
                      {modelGroups.map(g => (
                        <div key={g.provider_name}>
                          <div className="text-[10px] text-text-dim/70 font-semibold pt-1">{g.provider_name}</div>
                          {g.models.slice(0, 10).map(m => (
                            <div key={m.id} className="text-[10px] text-text-dim py-0.5 truncate" title={m.display}>{m.id}</div>
                          ))}
                          {g.models.length > 10 && (
                            <div className="text-[10px] text-text-dim/50 py-0.5">+{g.models.length - 10} more</div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  <CheckRow
                    label="Model Tiers"
                    count={TIER_ORDER.length}
                    checked={selected.has(KEY_TIERS)}
                    onToggle={() => toggle(KEY_TIERS)}
                    expanded={expanded.has(KEY_TIERS)}
                    onExpand={() => toggleExp(KEY_TIERS)}
                  />
                  {expanded.has(KEY_TIERS) && (
                    <div className="pl-9 pr-3 pb-1">
                      {TIER_ORDER.map(tier => {
                        const meta = TIER_LABELS[tier];
                        const entry = tiers[tier];
                        return (
                          <div key={tier} className="text-[10px] text-text-dim py-0.5 truncate" title={meta.hint}>
                            <span className="font-medium">{meta.label}</span>
                            <span className="text-text-dim/50"> → {entry?.model ?? "—"}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* --- Tools section --- */}
                  {toolGroups.length > 0 && (
                    <>
                      <SectionHeader label="Tools" />
                      {toolGroups.map(group => (
                        <div key={group.key}>
                          <CheckRow
                            label={group.label}
                            count={group.tools.length}
                            checked={selected.has(group.key)}
                            onToggle={() => toggle(group.key)}
                            expanded={expanded.has(group.key)}
                            onExpand={() => toggleExp(group.key)}
                          />
                          {expanded.has(group.key) && (
                            <div className="pl-9 pr-3 pb-1">
                              {group.tools.slice(0, 20).map(t => (
                                <div key={t.tool_key} className="text-[10px] text-text-dim py-0.5 truncate" title={t.description ?? t.tool_name}>
                                  {t.tool_name}
                                </div>
                              ))}
                              {group.tools.length > 20 && (
                                <div className="text-[10px] text-text-dim/50 py-0.5">+{group.tools.length - 20} more</div>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </>
                  )}

                  {toolGroups.length === 0 && !modelGroups?.length && (
                    <div className="px-3 py-4 text-[11px] text-text-dim text-center">No data loaded</div>
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

// ---------------------------------------------------------------------------
// Sidebar sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="px-3 py-1.5 mt-1 first:mt-0">
      <span className="text-[10px] font-bold text-text-dim/60 uppercase tracking-widest">{label}</span>
    </div>
  );
}

function CheckRow({ label, count, checked, onToggle, expanded, onExpand }: {
  label: string;
  count: number;
  checked: boolean;
  onToggle: () => void;
  expanded: boolean;
  onExpand: () => void;
}) {
  return (
    <div className="flex flex-row items-center gap-1.5 px-3 py-1.5 hover:bg-surface-raised/50 transition-colors">
      <button
        onClick={onExpand}
        className="p-0 bg-transparent border-none cursor-pointer text-text-dim hover:text-text shrink-0"
      >
        {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
      </button>
      <label className="flex flex-row items-center gap-2 flex-1 min-w-0 cursor-pointer">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="accent-accent shrink-0 w-3.5 h-3.5 cursor-pointer"
        />
        <span className="text-xs text-text truncate">{label}</span>
        <span className="text-[10px] text-text-dim ml-auto shrink-0">{count}</span>
      </label>
    </div>
  );
}
