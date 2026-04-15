/**
 * Memory + Knowledge sections for the bot editor.
 * Workspace-files is the only memory mode (DB memory is removed).
 */
import { useState } from "react";
import { ChevronDown, Clock, HelpCircle, Play, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useMemorySchemeDefaults } from "@/src/api/hooks/useMemorySchemeDefaults";
import { useMemoryHygieneStatus, useMemoryHygieneRuns, useTriggerMemoryHygiene } from "@/src/api/hooks/useMemoryHygiene";
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
│  ├── MEMORY.md           ← always in context (curated facts)    │
│  ├── logs/                                                       │
│  │   ├── 2026-03-28.md   ← auto-loaded (today)                 │
│  │   ├── 2026-03-27.md   ← auto-loaded (yesterday)             │
│  │   ├── *.md            ← searchable only                      │
│  │   └── archive/        ← old logs moved here by hygiene       │
│  └── reference/                                                  │
│      └── *.md            ← searchable only                      │
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
│  WRITING: bot uses exec_command (sed, echo, heredoc)              │
│                                                                    │
│  COMPACTION FLUSH: redirected to file writes                      │
│  SYSTEM PROMPT: built-in memory prompt auto-injected              │
└─────────────────────────────────────────────────────────────────┘

HOW IT WORKS

  Context injection (every turn):
    1. Read MEMORY.md from disk → inject as system message
    2. Read today's log (logs/YYYY-MM-DD.md) → inject as system message
    3. Read yesterday's log → inject as system message
    4. List reference/ files → inject filenames so bot knows what's available
    5. Exclude already-injected files from filesystem RAG (no duplication)

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
    Bot uses exec_command to write/edit files directly.
    No custom write tools — LLMs handle shell file ops well.
    File watcher detects changes → auto-reindex for search.

  Compaction flush:
    Before compaction runs, the bot is prompted to:
    - Append key decisions/events to today's daily log
    - Promote stable facts to MEMORY.md
    - Write anything needed for future conversations
`.trim();

const DIR_STRUCTURE = `memory/
├── MEMORY.md              # Always in context. Curated stable facts.
├── logs/
│   ├── YYYY-MM-DD.md      # Today + yesterday auto-loaded
│   ├── *.md               # Older logs searchable via search_memory
│   └── archive/           # Old logs moved here by hygiene
└── reference/
    └── *.md               # Longer docs, searchable + readable via tools`;

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
// Memory hygiene subsection
// ---------------------------------------------------------------------------
type DreamingJobTab = "maintenance" | "skill_review";

const JOB_TAB_CONFIG = {
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

function MemoryHygieneSubsection({ draft, update, botId }: {
  draft: BotConfig;
  update: (p: Partial<BotConfig>) => void;
  botId: string | undefined;
}) {
  const t = useThemeTokens();
  const { data: status } = useMemoryHygieneStatus(botId);
  const triggerMut = useTriggerMemoryHygiene();
  const [activeTab, setActiveTab] = useState<DreamingJobTab>("maintenance");
  const [showPrompt, setShowPrompt] = useState(false);
  const [showExtraInstr, setShowExtraInstr] = useState(false);

  const cfg = JOB_TAB_CONFIG[activeTab];
  const jobStatus = status?.[cfg.jobType === "memory_hygiene" ? "memory_hygiene" : "skill_review"];
  const { data: runsData } = useMemoryHygieneRuns(botId, cfg.jobType);

  const enabledValue = draft[cfg.fields.enabled];
  const resolvedEnabled = jobStatus?.enabled ?? false;
  const onlyActiveValue = draft[cfg.fields.only_if_active];
  const resolvedOnlyActive = jobStatus?.only_if_active ?? true;

  const fmtTime = (iso: string | null | undefined) => {
    if (!iso) return "Never";
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  };

  // Summary for tab cards
  const mhStatus = status?.memory_hygiene;
  const srStatus = status?.skill_review;

  return (
    <div className="rounded-lg border border-surface-raised bg-surface p-4">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <Clock size={14} color={t.purple} />
        <span className="text-[13px] font-semibold" style={{ color: t.text }}>Dreaming</span>
        <span className="text-[10px] flex-1 min-w-[200px]" style={{ color: t.textDim }}>
          Two scheduled jobs: lightweight maintenance (daily) and deeper skill review (less frequent).
        </span>
      </div>

      {/* Job selector cards */}
      <div className="grid grid-cols-2 gap-2 mb-4">
        {(["maintenance", "skill_review"] as const).map((tab) => {
          const tc = JOB_TAB_CONFIG[tab];
          const js = tab === "maintenance" ? mhStatus : srStatus;
          const isActive = activeTab === tab;
          return (
            <button
              key={tab}
              onClick={() => { setActiveTab(tab); setShowPrompt(false); setShowExtraInstr(false); }}
              className="text-left rounded-lg p-3 transition-all cursor-pointer"
              style={{
                background: isActive ? tc.accentSubtle : t.surfaceRaised,
                border: isActive ? `1.5px solid ${tc.accent}` : `1px solid ${t.surfaceBorder}`,
                borderLeft: isActive ? `3px solid ${tc.accent}` : `3px solid transparent`,
              }}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ background: js?.enabled ? tc.accent : t.textDim }}
                />
                <span className="text-[11px] font-semibold" style={{ color: isActive ? tc.accent : t.text }}>
                  {tc.shortLabel}
                </span>
              </div>
              <div className="text-[9px] leading-tight" style={{ color: t.textDim }}>
                {js?.enabled
                  ? `Every ${js.interval_hours}h${js.model ? ` · ${js.model.split("/").pop()}` : ""}`
                  : "Disabled"
                }
                {js?.next_run_at && js.enabled && (
                  <span className="block mt-0.5">Next: {fmtTime(js.next_run_at)}</span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Active tab config */}
      <div className="text-[10px] mb-3 leading-snug" style={{ color: t.textDim }}>
        {cfg.description}
      </div>

      {/* Enable selector */}
      <FormRow label="Enable">
        <div className="flex gap-1.5">
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
                className="px-2.5 py-1 rounded text-[11px] cursor-pointer transition-colors"
                style={{
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
          <FormRow label="Interval (hours)" description={`Global default: ${jobStatus?.interval_hours ?? 24}h`}>
            <TextInput
              value={String(draft[cfg.fields.interval] ?? "")}
              onChangeText={(v) => update({ [cfg.fields.interval]: v ? parseInt(v) : null } as any)}
              placeholder={String(jobStatus?.interval_hours ?? 24)}
              type="number"
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow
            label="Only if active"
            description="Skip if no user messages since last run."
          >
            <div className="flex gap-1.5">
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
                    className="px-2.5 py-1 rounded text-[11px] cursor-pointer transition-colors"
                    style={{
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
        description={`Bots stagger within ~60 min. ${jobStatus?.target_hour != null && jobStatus.target_hour >= 0 ? `Global: ${jobStatus.target_hour}:00` : "Global: disabled"}`}
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
          placeholder={jobStatus?.target_hour != null && jobStatus.target_hour >= 0 ? `${jobStatus.target_hour} (inherited)` : "Disabled (-1)"}
          type="number"
        />
      </FormRow>

      {/* Model override */}
      <FormRow label="Model" description={
        jobStatus?.model
          ? `Global: ${jobStatus.model}${draft[cfg.fields.model] ? " (overridden)" : ""}`
          : "No global default — uses bot's model"
      }>
        <LlmModelDropdown
          value={draft[cfg.fields.model] ?? ""}
          onChange={(modelId, providerId) => update({
            [cfg.fields.model]: modelId || null,
            [cfg.fields.model_provider]: providerId ?? null,
          } as any)}
          placeholder={jobStatus?.model || "bot default"}
          selectedProviderId={draft[cfg.fields.model_provider]}
          allowClear
        />
      </FormRow>

      {/* Additional instructions (appended to base prompt) */}
      <div className="mt-2">
        <button
          onClick={() => setShowExtraInstr(!showExtraInstr)}
          className="flex items-center gap-1.5 w-full py-1.5 bg-transparent border-none cursor-pointer text-[11px] font-semibold"
          style={{ color: t.textMuted }}
        >
          <ChevronDown
            size={12}
            style={{ transform: showExtraInstr ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
          />
          Additional Instructions
          {draft[cfg.fields.extra_instructions] && (
            <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: cfg.accentSubtle, color: cfg.accent }}>
              custom
            </span>
          )}
        </button>
        {showExtraInstr && (
          <div className="mt-1.5">
            <textarea
              value={draft[cfg.fields.extra_instructions] || ""}
              onChange={(e) => update({ [cfg.fields.extra_instructions]: e.target.value || null } as any)}
              rows={3}
              placeholder="Appended to the built-in prompt. E.g., &quot;Use firecrawl tool for research&quot;..."
              className="w-full rounded-md px-3 py-2 text-[11px] resize-y"
              style={{
                background: t.inputBg, border: `1px solid ${t.inputBorder}`, color: t.inputText,
                fontFamily: "inherit", lineHeight: 1.5,
              }}
            />
            <div className="text-[9px] mt-1" style={{ color: t.textDim }}>
              These are appended to the built-in prompt — they don't replace it.
            </div>
          </div>
        )}
      </div>

      {/* Full prompt override (collapsible — secondary) */}
      <div className="mt-1">
        <button
          onClick={() => setShowPrompt(!showPrompt)}
          className="flex items-center gap-1.5 w-full py-1.5 bg-transparent border-none cursor-pointer text-[11px] font-semibold"
          style={{ color: t.textDim }}
        >
          <ChevronDown
            size={12}
            style={{ transform: showPrompt ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
          />
          Full Prompt Override
          {draft[cfg.fields.prompt] && (
            <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: t.warningSubtle, color: t.warning }}>
              overridden
            </span>
          )}
        </button>
        {showPrompt && (
          <div className="mt-1.5">
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
                className="mt-1 px-2 py-0.5 rounded text-[10px] cursor-pointer"
                style={{ background: "none", border: `1px solid ${t.surfaceOverlay}`, color: t.textDim }}
              >
                Reset to default
              </button>
            )}
          </div>
        )}
      </div>

      {/* Built-in prompt preview */}
      {!draft[cfg.fields.prompt] && jobStatus?.resolved_prompt && (
        <BuiltinPromptCollapsible
          label={`Built-in ${cfg.shortLabel} Prompt`}
          content={jobStatus.resolved_prompt}
        />
      )}

      {/* Status line + Run Now */}
      {botId && jobStatus && (
        <div className="mt-3 pt-2.5 flex items-center justify-between" style={{ borderTop: `1px solid ${t.surfaceOverlay}` }}>
          <div className="text-[10px] leading-relaxed" style={{ color: t.textDim }}>
            Last run: {fmtTime(jobStatus.last_run_at)}
            {jobStatus.last_task_status && (
              <span className="ml-1.5 px-1.5 py-0.5 rounded text-[9px]" style={{
                background: jobStatus.last_task_status === "complete" ? t.successSubtle : t.surfaceOverlay,
                color: jobStatus.last_task_status === "complete" ? t.success : t.textDim,
              }}>
                {jobStatus.last_task_status}
              </span>
            )}
            <br />
            Next run: {fmtTime(jobStatus.next_run_at)}
          </div>
          <button
            onClick={() => botId && triggerMut.mutate({ botId, jobType: cfg.jobType })}
            disabled={triggerMut.isPending}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-medium cursor-pointer transition-opacity"
            style={{
              background: cfg.accentSubtle, border: `1px solid ${cfg.accentBorder}`,
              color: cfg.accent, opacity: triggerMut.isPending ? 0.6 : 1,
            }}
          >
            <Play size={10} />
            {triggerMut.isPending ? "Running..." : "Run Now"}
          </button>
        </div>
      )}

      {/* Run history */}
      {botId && runsData && runsData.runs.length > 0 && (
        <div className="mt-3">
          <HygieneHistoryList runs={runsData.runs} />
        </div>
      )}
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
// Knowledge section — managed by workspace files
// ---------------------------------------------------------------------------
export function KnowledgeSection() {
  const t = useThemeTokens();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Knowledge</div>
      <div style={{
        background: t.purpleSubtle, border: `1px solid ${t.purpleBorder}`,
        borderRadius: 8, padding: "14px 16px",
      }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: t.purple }}>
            Managed by Workspace Files
          </span>
        </div>
        <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6 }}>
          Knowledge lives in <code style={{ color: t.purpleMuted }}>memory/reference/</code> files.
          Searchable via <code style={{ color: t.purpleMuted }}>search_memory</code> and readable
          via <code style={{ color: t.purpleMuted }}>get_memory_file</code>. DB knowledge tools are
          hidden automatically.
        </div>
      </div>
    </div>
  );
}
