/**
 * Memory + Knowledge sections for the bot editor.
 * Workspace-files is the only memory mode (DB memory is removed).
 */
import { useState } from "react";
import { ChevronDown, Clock, HelpCircle, Play, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useMemorySchemeDefaults } from "@/src/api/hooks/useMemorySchemeDefaults";
import { useMemoryHygieneStatus, useMemoryHygieneRuns, useTriggerMemoryHygiene, type JobStatus } from "@/src/api/hooks/useMemoryHygiene";
import { HygieneHistoryList } from "./HygieneHistoryList";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  TextInput, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import type { BotConfig } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const ARCHITECTURE_DIAGRAM = `
┌─────────────────────────────────────────────────────────────────┐
│                    WORKSPACE FILES MEMORY MODE                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  memory/                                                         │
│  ├── MEMORY.md           ← durable baseline in context          │
│  ├── logs/                                                       │
│  │   ├── 2026-03-28.md   ← often hot in normal chat            │
│  │   ├── 2026-03-27.md   ← often hot in normal chat            │
│  │   ├── *.md            ← searchable only                      │
│  │   └── archive/        ← old logs moved here by hygiene       │
│  └── reference/                                                  │
│      └── *.md            ← listed/readable via tools            │
│                                                                  │
│  ┌─────────────────┐  ┌──────────────────────────────┐          │
│  │  search_memory   │  │  get_memory_file              │          │
│  │  (hybrid search) │  │  (read by name)               │          │
│  │  vector + BM25   │  │  shorthand resolution         │          │
│  │  RRF merge       │  │  path traversal protection    │          │
│  └────────┬─────────┘  └──────────────────────────────┘          │
│           │                                                       │
│  ┌────────▼──────────────────────────────────────┐               │
│  │  filesystem_chunks (pgvector + tsvector)       │               │
│  │  ← indexed by existing fs_indexer pipeline     │               │
│  │  ← file watcher auto-reindexes on change       │               │
│  └────────────────────────────────────────────────┘               │
│                                                                    │
│  WRITING: bot uses the file tool (edit, append, create, overwrite)│
│                                                                    │
│  COMPACTION FLUSH: redirected to file writes                      │
│  SYSTEM PROMPT: built-in memory prompt auto-injected              │
└─────────────────────────────────────────────────────────────────┘

HOW IT WORKS

  Context admission (profile first, budget second):
    1. Read MEMORY.md from disk → inject as a durable baseline
    2. Optionally inject today's log → profile/budget gated
    3. Optionally inject yesterday's log → profile/budget gated
    4. Optionally list reference/ files so bot knows what's available
    5. Exclude already-admitted files from filesystem RAG (no duplication)

  Search (search_memory tool):
    Hybrid retrieval over all memory files:
    ┌─────────────┐   ┌───────────────┐
    │ Vector hits  │   │ Full-text hits │
    │ (pgvector    │   │ (tsvector      │
    │  cosine sim) │   │  BM25 rank)    │
    └──────┬───────┘   └──────┬─────────┘
           │                  │
           └────────┬─────────┘
                    │
           Reciprocal Rank Fusion (k=60)
                    │
              Top-K results

  Writing:
    Bot uses the file tool to write/edit files directly.
    File watcher detects changes → auto-reindex for search.

  Compaction flush:
    Before compaction runs, the bot is prompted to:
    - Append key decisions/events to today's daily log
    - Promote stable facts to MEMORY.md
    - Write anything needed for future conversations
`.trim();

const DIR_STRUCTURE = `memory/
├── MEMORY.md              # Durable baseline in context.
├── logs/
│   ├── YYYY-MM-DD.md      # Today + yesterday often hot in normal chat
│   ├── *.md               # Older logs searchable via search_memory
│   └── archive/           # Old logs moved here by hygiene
└── reference/
    └── *.md               # Longer docs, listed + readable via tools`;

// ---------------------------------------------------------------------------
// Architecture help overlay
// ---------------------------------------------------------------------------
function ArchitectureOverlay({ onClose }: { onClose: () => void }) {
  const t = useThemeTokens();
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 100,
        background: "rgba(0,0,0,0.75)", backdropFilter: "blur(4px)",
        display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
        padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: t.surface, border: `1px solid ${t.surfaceOverlay}`,
          borderRadius: 12, maxWidth: 780, width: "100%",
          maxHeight: "90vh", overflow: "auto",
        }}
      >
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between",
          padding: "14px 18px", borderBottom: `1px solid ${t.surfaceRaised}`,
        }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
            Workspace Files Memory — Architecture
          </span>
          <button
            onClick={onClose}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: t.textDim, padding: 4,
            }}
          >
            <X size={16} />
          </button>
        </div>
        <pre style={{
          margin: 0, padding: "16px 20px",
          fontSize: 11, lineHeight: 1.6, color: t.textMuted,
          fontFamily: "monospace", whiteSpace: "pre",
          overflowX: "auto",
        }}>{ARCHITECTURE_DIAGRAM}</pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reusable collapsible for showing built-in prompt text
// ---------------------------------------------------------------------------
function BuiltinPromptCollapsible({ label, content }: { label: string; content: string }) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);

  return (
    <div style={{
      marginTop: 8, background: t.surface,
      border: `1px solid ${t.surfaceRaised}`, borderRadius: 8, overflow: "hidden",
    }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 8, width: "100%",
          padding: "8px 12px", background: "none", border: "none",
          cursor: "pointer", color: t.textMuted,
        }}
      >
        <ChevronDown
          size={12}
          style={{ transform: open ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
        />
        <span style={{ fontSize: 11, fontWeight: 600 }}>{label}</span>
        <span style={{
          fontSize: 9, padding: "2px 6px", borderRadius: 3,
          background: t.purpleSubtle, color: t.purpleMuted,
          marginLeft: 4,
        }}>auto-injected</span>
      </button>
      {open && (
        <div style={{ padding: "0 12px 10px 12px" }}>
          <pre style={{
            margin: 0, fontSize: 11, lineHeight: 1.7, color: t.textMuted,
            fontFamily: "monospace", whiteSpace: "pre-wrap",
            background: t.inputBg, borderRadius: 6, padding: 12,
          }}>{content}</pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Memory hygiene subsection — two stacked collapsible job sections
// ---------------------------------------------------------------------------

const JOB_CONFIG = {
  maintenance: {
    label: "Memory Maintenance",
    shortLabel: "Maintenance",
    description: "Daily file tidying — curates MEMORY.md, promotes facts, archives old logs.",
    accent: "#f59e0b",
    accentSubtle: "rgba(245,158,11,0.08)",
    accentBorder: "rgba(245,158,11,0.2)",
    jobType: "memory_hygiene" as const,
    fields: {
      enabled: "memory_hygiene_enabled" as const,
      interval: "memory_hygiene_interval_hours" as const,
      only_if_active: "memory_hygiene_only_if_active" as const,
      target_hour: "memory_hygiene_target_hour" as const,
      model: "memory_hygiene_model" as const,
      model_provider: "memory_hygiene_model_provider_id" as const,
      prompt: "memory_hygiene_prompt" as const,
      extra_instructions: "memory_hygiene_extra_instructions" as const,
    },
  },
  skill_review: {
    label: "Skill Review",
    shortLabel: "Skill Review",
    description: "Periodic reasoning — cross-channel reflection, skill pruning, auto-inject audit.",
    accent: "#8b5cf6",
    accentSubtle: "rgba(139,92,246,0.08)",
    accentBorder: "rgba(139,92,246,0.2)",
    jobType: "skill_review" as const,
    fields: {
      enabled: "skill_review_enabled" as const,
      interval: "skill_review_interval_hours" as const,
      only_if_active: "skill_review_only_if_active" as const,
      target_hour: "skill_review_target_hour" as const,
      model: "skill_review_model" as const,
      model_provider: "skill_review_model_provider_id" as const,
      prompt: "skill_review_prompt" as const,
      extra_instructions: "skill_review_extra_instructions" as const,
    },
  },
} as const;

type JobKey = keyof typeof JOB_CONFIG;

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Single job section — self-contained header + collapsible config
// ---------------------------------------------------------------------------
function JobSection({ jobKey, draft, update, botId, status, triggerMut }: {
  jobKey: JobKey;
  draft: BotConfig;
  update: (p: Partial<BotConfig>) => void;
  botId: string | undefined;
  status: JobStatus | undefined;
  triggerMut: ReturnType<typeof useTriggerMemoryHygiene>;
}) {
  const t = useThemeTokens();
  const cfg = JOB_CONFIG[jobKey];
  const [expanded, setExpanded] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [showExtraInstr, setShowExtraInstr] = useState(false);
  const { data: runsData } = useMemoryHygieneRuns(botId, cfg.jobType);

  const enabledValue = draft[cfg.fields.enabled];
  const resolvedEnabled = status?.enabled ?? false;
  const onlyActiveValue = draft[cfg.fields.only_if_active];
  const resolvedOnlyActive = status?.only_if_active ?? true;

  return (
    <div style={{
      borderRadius: 8, overflow: "hidden",
      border: `1px solid ${t.surfaceBorder}`,
      borderLeft: `3px solid ${cfg.accent}`,
    }}>
      {/* Always-visible header */}
      <div style={{
        padding: "10px 14px",
        background: cfg.accentSubtle,
      }}>
        {/* Top row: label + status dot + summary */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{
            width: 7, height: 7, borderRadius: "50%", flexShrink: 0,
            background: resolvedEnabled ? cfg.accent : t.textDim,
          }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{cfg.label}</span>
          <span style={{ fontSize: 10, color: t.textDim }}>
            {resolvedEnabled
              ? `Every ${status?.interval_hours ?? "?"}h${status?.model ? ` · ${status.model.split("/").pop()}` : ""}`
              : "Disabled"
            }
          </span>
        </div>

        {/* Status line + Run Now */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ fontSize: 10, color: t.textDim }}>
            Last: {fmtTime(status?.last_run_at)}
            {status?.last_task_status && (
              <span style={{
                marginLeft: 6, padding: "1px 6px", borderRadius: 3, fontSize: 9,
                background: status.last_task_status === "complete" ? t.successSubtle
                  : status.last_task_status === "failed" ? t.dangerSubtle : t.surfaceOverlay,
                color: status.last_task_status === "complete" ? t.success
                  : status.last_task_status === "failed" ? t.danger : t.textDim,
              }}>
                {status.last_task_status}
              </span>
            )}
            <span style={{ margin: "0 6px", color: t.surfaceBorder }}>·</span>
            Next: {fmtTime(status?.next_run_at)}
          </div>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
            {botId && (
              <button
                onClick={() => triggerMut.mutate({ botId, jobType: cfg.jobType })}
                disabled={triggerMut.isPending}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                  padding: "3px 10px", borderRadius: 4, fontSize: 10, fontWeight: 500,
                  cursor: triggerMut.isPending ? "not-allowed" : "pointer",
                  background: cfg.accentSubtle, border: `1px solid ${cfg.accentBorder}`,
                  color: cfg.accent, opacity: triggerMut.isPending ? 0.6 : 1,
                }}
              >
                <Play size={9} />
                Run Now
              </button>
            )}
            <button
              onClick={() => setExpanded(!expanded)}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
                padding: "3px 10px", borderRadius: 4, fontSize: 10, fontWeight: 500,
                cursor: "pointer", background: "none",
                border: `1px solid ${t.surfaceBorder}`, color: t.textMuted,
              }}
            >
              <ChevronDown
                size={10}
                style={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.15s" } as any}
              />
              Configure
            </button>
          </div>
        </div>
      </div>

      {/* Collapsible config body */}
      {expanded && (
        <div style={{ padding: "12px 14px", background: t.surface }}>
          <div style={{ fontSize: 10, color: t.textDim, marginBottom: 10, lineHeight: "15px" }}>
            {cfg.description}
          </div>

          {/* Enable selector */}
          <FormRow label="Enable">
            <div style={{ display: "flex", flexDirection: "row", gap: 6 }}>
              {([undefined, true, false] as const).map((val) => {
                const isSelected =
                  val === undefined
                    ? enabledValue === null || enabledValue === undefined
                    : enabledValue === val;
                const label =
                  val === undefined
                    ? `Inherit (${resolvedEnabled ? "On" : "Off"})`
                    : val ? "Enabled" : "Disabled";
                return (
                  <button
                    key={String(val)}
                    onClick={() => update({ [cfg.fields.enabled]: val === undefined ? null : val } as any)}
                    style={{
                      padding: "4px 10px", borderRadius: 4, fontSize: 11, cursor: "pointer",
                      border: isSelected ? `1px solid ${cfg.accent}` : `1px solid ${t.surfaceOverlay}`,
                      background: isSelected ? cfg.accentSubtle : "transparent",
                      color: isSelected ? cfg.accent : t.textMuted,
                      fontWeight: isSelected ? 600 : 400,
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </FormRow>

          <Row>
            <Col>
              <FormRow label="Interval (hours)" description={`Global default: ${status?.interval_hours ?? 24}h`}>
                <TextInput
                  value={String(draft[cfg.fields.interval] ?? "")}
                  onChangeText={(v) => update({ [cfg.fields.interval]: v ? parseInt(v) : null } as any)}
                  placeholder={String(status?.interval_hours ?? 24)}
                  type="number"
                />
              </FormRow>
            </Col>
            <Col>
              <FormRow label="Only if active" description="Skip if no user messages since last run.">
                <div style={{ display: "flex", flexDirection: "row", gap: 6 }}>
                  {([undefined, true, false] as const).map((val) => {
                    const isSelected =
                      val === undefined
                        ? onlyActiveValue === null || onlyActiveValue === undefined
                        : onlyActiveValue === val;
                    const label =
                      val === undefined
                        ? `Inherit (${resolvedOnlyActive ? "Yes" : "No"})`
                        : val ? "Yes" : "No";
                    return (
                      <button
                        key={String(val)}
                        onClick={() => update({ [cfg.fields.only_if_active]: val === undefined ? null : val } as any)}
                        style={{
                          padding: "4px 10px", borderRadius: 4, fontSize: 11, cursor: "pointer",
                          border: isSelected ? `1px solid ${cfg.accent}` : `1px solid ${t.surfaceOverlay}`,
                          background: isSelected ? cfg.accentSubtle : "transparent",
                          color: isSelected ? cfg.accent : t.textMuted,
                          fontWeight: isSelected ? 600 : 400,
                        }}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
              </FormRow>
            </Col>
          </Row>

          {/* Target hour */}
          <FormRow
            label="Target Start Hour (local time)"
            description={`Bots stagger within ~60 min. ${status?.target_hour != null && status.target_hour >= 0 ? `Global: ${status.target_hour}:00` : "Global: disabled"}`}
          >
            <TextInput
              value={draft[cfg.fields.target_hour] != null ? String(draft[cfg.fields.target_hour]) : ""}
              onChangeText={(v) => {
                if (v === "" || v === "-1") {
                  update({ [cfg.fields.target_hour]: v === "-1" ? -1 : null } as any);
                } else {
                  const n = parseInt(v);
                  if (!isNaN(n) && n >= -1 && n <= 23) update({ [cfg.fields.target_hour]: n } as any);
                }
              }}
              placeholder={status?.target_hour != null && status.target_hour >= 0 ? `${status.target_hour} (inherited)` : "Disabled (-1)"}
              type="number"
            />
          </FormRow>

          {/* Model override */}
          <FormRow label="Model" description={
            status?.model
              ? `Global: ${status.model}${draft[cfg.fields.model] ? " (overridden)" : ""}`
              : "No global default — uses bot's model"
          }>
            <LlmModelDropdown
              value={draft[cfg.fields.model] ?? ""}
              onChange={(modelId, providerId) => update({
                [cfg.fields.model]: modelId || null,
                [cfg.fields.model_provider]: providerId ?? null,
              } as any)}
              placeholder={status?.model || "bot default"}
              selectedProviderId={draft[cfg.fields.model_provider]}
              allowClear
            />
          </FormRow>

          {/* Additional instructions */}
          <div style={{ marginTop: 8 }}>
            <button
              onClick={() => setShowExtraInstr(!showExtraInstr)}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                width: "100%", padding: "6px 0", background: "none", border: "none",
                cursor: "pointer", fontSize: 11, fontWeight: 600, color: t.textMuted,
              }}
            >
              <ChevronDown
                size={12}
                style={{ transform: showExtraInstr ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
              />
              Additional Instructions
              {draft[cfg.fields.extra_instructions] && (
                <span style={{
                  fontSize: 9, padding: "1px 6px", borderRadius: 3,
                  background: cfg.accentSubtle, color: cfg.accent,
                }}>custom</span>
              )}
            </button>
            {showExtraInstr && (
              <div style={{ marginTop: 6 }}>
                <textarea
                  value={draft[cfg.fields.extra_instructions] || ""}
                  onChange={(e) => update({ [cfg.fields.extra_instructions]: e.target.value || null } as any)}
                  rows={3}
                  placeholder="Appended to the built-in prompt. E.g., &quot;Use firecrawl tool for research&quot;..."
                  style={{
                    width: "100%", borderRadius: 6, padding: "8px 12px", fontSize: 11,
                    resize: "vertical", fontFamily: "inherit", lineHeight: 1.5,
                    background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.inputText,
                    boxSizing: "border-box",
                  }}
                />
                <div style={{ fontSize: 9, marginTop: 4, color: t.textDim }}>
                  These are appended to the built-in prompt — they don't replace it.
                </div>
              </div>
            )}
          </div>

          {/* Full prompt override */}
          <div style={{ marginTop: 4 }}>
            <button
              onClick={() => setShowPrompt(!showPrompt)}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                width: "100%", padding: "6px 0", background: "none", border: "none",
                cursor: "pointer", fontSize: 11, fontWeight: 600, color: t.textDim,
              }}
            >
              <ChevronDown
                size={12}
                style={{ transform: showPrompt ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
              />
              Full Prompt Override
              {draft[cfg.fields.prompt] && (
                <span style={{
                  fontSize: 9, padding: "1px 6px", borderRadius: 3,
                  background: t.warningSubtle, color: t.warning,
                }}>overridden</span>
              )}
            </button>
            {showPrompt && (
              <div style={{ marginTop: 6 }}>
                <LlmPrompt
                  value={draft[cfg.fields.prompt] || ""}
                  onChange={(v) => update({ [cfg.fields.prompt]: v || null } as any)}
                  rows={6}
                  placeholder="Leave empty to use the built-in default prompt..."
                  fieldType={cfg.fields.prompt}
                  botId={botId}
                />
                {draft[cfg.fields.prompt] && (
                  <button
                    onClick={() => update({ [cfg.fields.prompt]: null } as any)}
                    style={{
                      marginTop: 4, padding: "2px 8px", borderRadius: 4, fontSize: 10,
                      cursor: "pointer", background: "none",
                      border: `1px solid ${t.surfaceOverlay}`, color: t.textDim,
                    }}
                  >
                    Reset to default
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Built-in prompt preview */}
          {!draft[cfg.fields.prompt] && status?.resolved_prompt && (
            <BuiltinPromptCollapsible
              label={`Built-in ${cfg.shortLabel} Prompt`}
              content={status.resolved_prompt}
            />
          )}

          {/* Run history */}
          {botId && runsData && runsData.runs.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <HygieneHistoryList runs={runsData.runs} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main dreaming subsection — renders two JobSections stacked
// ---------------------------------------------------------------------------
function MemoryHygieneSubsection({ draft, update, botId }: {
  draft: BotConfig;
  update: (p: Partial<BotConfig>) => void;
  botId: string | undefined;
}) {
  const t = useThemeTokens();
  const { data: status } = useMemoryHygieneStatus(botId);
  const triggerMut = useTriggerMemoryHygiene();

  return (
    <div style={{
      borderRadius: 8, padding: 16,
      background: t.surface, border: `1px solid ${t.surfaceRaised}`,
    }}>
      {/* Header */}
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <Clock size={14} color={t.purple} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>Dreaming</span>
      </div>
      <div style={{ fontSize: 10, color: t.textDim, marginBottom: 14, lineHeight: "15px" }}>
        Two scheduled jobs: lightweight maintenance (daily) and deeper skill review (less frequent).
      </div>

      {/* Stacked job sections */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <JobSection
          jobKey="maintenance"
          draft={draft} update={update} botId={botId}
          status={status?.memory_hygiene}
          triggerMut={triggerMut}
        />
        <JobSection
          jobKey="skill_review"
          draft={draft} update={update} botId={botId}
          status={status?.skill_review}
          triggerMut={triggerMut}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Memory section — workspace files mode (only mode)
// ---------------------------------------------------------------------------
export function MemorySection({ draft, update, botId }: {
  draft: BotConfig;
  update: (p: Partial<BotConfig>) => void;
  botId: string | undefined;
}) {
  const t = useThemeTokens();
  const { data: defaults } = useMemorySchemeDefaults();
  const builtInPrompt = defaults?.prompt ?? "";
  const [showPrompt, setShowPrompt] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Memory</div>
        <button
          onClick={() => setShowHelp(true)}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: t.textDim, padding: 2, display: "flex", flexDirection: "row", alignItems: "center",
          }}
          title="How workspace files memory works"
        >
          <HelpCircle size={15} />
        </button>
      </div>
      {showHelp && <ArchitectureOverlay onClose={() => setShowHelp(false)} />}

      {/* Directory structure preview */}
      <div style={{
        background: t.surface, border: `1px solid ${t.surfaceRaised}`,
        borderRadius: 8, padding: "12px 16px",
      }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, marginBottom: 8 }}>
          Directory Structure
        </div>
        <pre style={{
          margin: 0, fontSize: 11, lineHeight: 1.7, color: t.textMuted,
          fontFamily: "monospace",
        }}>{DIR_STRUCTURE}</pre>
      </div>

      {/* Built-in prompt (collapsible) */}
      <div style={{
        background: t.surface, border: `1px solid ${t.surfaceRaised}`,
        borderRadius: 8, overflow: "hidden",
      }}>
        <button
          onClick={() => setShowPrompt(!showPrompt)}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 8, width: "100%",
            padding: "10px 16px", background: "none", border: "none",
            cursor: "pointer", color: t.textMuted,
          }}
        >
          <ChevronDown
            size={14}
            style={{ transform: showPrompt ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
          />
          <span style={{ fontSize: 12, fontWeight: 600 }}>Built-in System Prompt</span>
          <span style={{
            fontSize: 9, padding: "2px 6px", borderRadius: 3,
            background: t.purpleSubtle, color: t.purpleMuted,
            marginLeft: 4,
          }}>auto-injected</span>
        </button>
        {showPrompt && (
          <div style={{ padding: "0 16px 14px 16px" }}>
            <pre style={{
              margin: 0, fontSize: 11, lineHeight: 1.7, color: t.textMuted,
              fontFamily: "monospace", whiteSpace: "pre-wrap",
              background: t.inputBg, borderRadius: 6, padding: 12,
            }}>{builtInPrompt}</pre>
          </div>
        )}
      </div>

      {/* Dreaming (Memory Hygiene) */}
      <MemoryHygieneSubsection draft={draft} update={update} botId={botId} />
    </div>
  );
}

// ---------------------------------------------------------------------------
