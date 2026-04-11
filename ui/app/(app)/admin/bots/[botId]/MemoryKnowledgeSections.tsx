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
        display: "flex", alignItems: "center", justifyContent: "center",
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
          display: "flex", alignItems: "center", justifyContent: "space-between",
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
          display: "flex", alignItems: "center", gap: 8, width: "100%",
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
function MemoryHygieneSubsection({ draft, update, botId }: {
  draft: BotConfig;
  update: (p: Partial<BotConfig>) => void;
  botId: string | undefined;
}) {
  const t = useThemeTokens();
  const { data: status } = useMemoryHygieneStatus(botId);
  const { data: runsData } = useMemoryHygieneRuns(botId);
  const triggerMut = useTriggerMemoryHygiene();
  const [showPrompt, setShowPrompt] = useState(false);

  // Three-state: null = inherit global, true = enabled, false = disabled
  const enabledValue = draft.memory_hygiene_enabled;
  const resolvedEnabled = status?.enabled ?? false;

  const onlyActiveValue = draft.memory_hygiene_only_if_active;
  const resolvedOnlyActive = status?.only_if_active ?? true;

  const fmtTime = (iso: string | null | undefined) => {
    if (!iso) return "Never";
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  };

  return (
    <div style={{
      background: t.surface, border: `1px solid ${t.surfaceRaised}`,
      borderRadius: 8, padding: "14px 16px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <Clock size={14} color={t.purple} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
          Dreaming
        </span>
        <span style={{ fontSize: 10, color: t.textDim, flex: 1, minWidth: 200 }}>
          Scheduled background review — curates MEMORY.md, promotes facts from daily logs, detects contradictions, generates reflections, and consolidates skills across all channels.
        </span>
        {status?.next_run_at && (
          <span style={{
            fontSize: 10, color: t.purple, fontWeight: 500,
            padding: "2px 8px", borderRadius: 4,
            background: t.purpleSubtle, border: `1px solid ${t.purpleBorder}`,
            whiteSpace: "nowrap",
          }}>
            Next: {fmtTime(status.next_run_at)}
          </span>
        )}
      </div>

      {/* Enable selector */}
      <FormRow label="Enable">
        <div style={{ display: "flex", gap: 6 }}>
          {([undefined, true, false] as const).map((val) => {
            const isSelected =
              val === undefined
                ? enabledValue === null || enabledValue === undefined
                : enabledValue === val;
            const label =
              val === undefined
                ? `Inherit (${resolvedEnabled ? "On" : "Off"})`
                : val
                  ? "Enabled"
                  : "Disabled";
            return (
              <button
                key={String(val)}
                onClick={() => update({ memory_hygiene_enabled: val === undefined ? null : val })}
                style={{
                  padding: "4px 10px", borderRadius: 4, fontSize: 11,
                  border: isSelected ? `1px solid ${t.accent}` : `1px solid ${t.surfaceOverlay}`,
                  background: isSelected ? t.accentSubtle : "transparent",
                  color: isSelected ? t.accent : t.textMuted,
                  cursor: "pointer", fontWeight: isSelected ? 600 : 400,
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
              value={String(draft.memory_hygiene_interval_hours ?? "")}
              onChangeText={(v) => update({ memory_hygiene_interval_hours: v ? parseInt(v) : null })}
              placeholder={String(status?.interval_hours ?? 24)}
              type="number"
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow
            label="Only if active"
            description="Skip when no user messages have landed in this bot's channels (primary or member) since the last run. Bot-to-bot delegation, heartbeats, and assistant replies don't count as activity — a bot whose channels only see bot traffic will never dream unless this is set to No."
          >
            <div style={{ display: "flex", gap: 6 }}>
              {([undefined, true, false] as const).map((val) => {
                const isSelected =
                  val === undefined
                    ? onlyActiveValue === null || onlyActiveValue === undefined
                    : onlyActiveValue === val;
                const label =
                  val === undefined
                    ? `Inherit (${resolvedOnlyActive ? "Yes" : "No"})`
                    : val
                      ? "Yes"
                      : "No";
                return (
                  <button
                    key={String(val)}
                    onClick={() => update({ memory_hygiene_only_if_active: val === undefined ? null : val })}
                    style={{
                      padding: "4px 10px", borderRadius: 4, fontSize: 11,
                      border: isSelected ? `1px solid ${t.accent}` : `1px solid ${t.surfaceOverlay}`,
                      background: isSelected ? t.accentSubtle : "transparent",
                      color: isSelected ? t.accent : t.textMuted,
                      cursor: "pointer", fontWeight: isSelected ? 600 : 400,
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
        description={`Bots stagger within ~60 min of this hour. ${status?.target_hour != null && status.target_hour >= 0 ? `Global: ${status.target_hour}:00` : "Global: disabled"}`}
      >
        <TextInput
          value={draft.memory_hygiene_target_hour != null ? String(draft.memory_hygiene_target_hour) : ""}
          onChangeText={(v) => {
            if (v === "" || v === "-1") {
              update({ memory_hygiene_target_hour: v === "-1" ? -1 : null });
            } else {
              const n = parseInt(v);
              if (!isNaN(n) && n >= -1 && n <= 23) update({ memory_hygiene_target_hour: n });
            }
          }}
          placeholder={status?.target_hour != null && status.target_hour >= 0 ? `${status.target_hour} (inherited)` : "Disabled (-1)"}
          type="number"
        />
      </FormRow>

      {/* Model override */}
      <FormRow label="Model" description={
        status?.model
          ? `Global: ${status.model}${draft.memory_hygiene_model ? " (overridden)" : ""}`
          : "No global default — uses bot's model"
      }>
        <LlmModelDropdown
          value={draft.memory_hygiene_model ?? ""}
          onChange={(modelId, providerId) => update({
            memory_hygiene_model: modelId || null,
            memory_hygiene_model_provider_id: providerId ?? null,
          })}
          placeholder={status?.model || "bot default"}
          selectedProviderId={draft.memory_hygiene_model_provider_id}
          allowClear
        />
      </FormRow>

      {/* Custom prompt override (collapsible) */}
      <div style={{ marginTop: 8 }}>
        <button
          onClick={() => setShowPrompt(!showPrompt)}
          style={{
            display: "flex", alignItems: "center", gap: 6, width: "100%",
            padding: "6px 0", background: "none", border: "none",
            cursor: "pointer", color: t.textMuted, fontSize: 11, fontWeight: 600,
          }}
        >
          <ChevronDown
            size={12}
            style={{ transform: showPrompt ? "rotate(0deg)" : "rotate(-90deg)", transition: "transform 0.15s" } as any}
          />
          Custom Prompt Override
          {draft.memory_hygiene_prompt && (
            <span style={{
              fontSize: 9, padding: "1px 5px", borderRadius: 3,
              background: t.purpleSubtle, color: t.purple,
            }}>custom</span>
          )}
        </button>
        {showPrompt && (
          <div style={{ marginTop: 6 }}>
            <LlmPrompt
              value={draft.memory_hygiene_prompt || ""}
              onChange={(v) => update({ memory_hygiene_prompt: v || null })}
              rows={6}
              placeholder="Leave empty to use the built-in default prompt..."
              fieldType="memory_hygiene_prompt"
              botId={botId}
            />
            {draft.memory_hygiene_prompt && (
              <button
                onClick={() => update({ memory_hygiene_prompt: null })}
                style={{
                  marginTop: 4, padding: "3px 8px", borderRadius: 4,
                  background: "none", border: `1px solid ${t.surfaceOverlay}`,
                  color: t.textDim, fontSize: 10, cursor: "pointer",
                }}
              >
                Reset to default
              </button>
            )}
          </div>
        )}
      </div>

      {/* Built-in hygiene prompt (collapsible, shown when no custom override) */}
      {!draft.memory_hygiene_prompt && status?.resolved_prompt && (
        <BuiltinPromptCollapsible label="Built-in Dreaming Prompt" content={status.resolved_prompt} />
      )}

      {/* Status line + Run Now */}
      {botId && status && (
        <div style={{
          marginTop: 12, paddingTop: 10,
          borderTop: `1px solid ${t.surfaceOverlay}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div style={{ fontSize: 10, color: t.textDim, lineHeight: 1.6 }}>
            Last run: {fmtTime(status.last_run_at)}
            {status.last_task_status && (
              <span style={{
                marginLeft: 6, padding: "1px 5px", borderRadius: 3, fontSize: 9,
                background: status.last_task_status === "complete" ? t.successSubtle : t.surfaceOverlay,
                color: status.last_task_status === "complete" ? t.success : t.textDim,
              }}>
                {status.last_task_status}
              </span>
            )}
            <br />
            Next run: {fmtTime(status.next_run_at)}
          </div>
          <button
            onClick={() => botId && triggerMut.mutate(botId)}
            disabled={triggerMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "5px 10px", borderRadius: 5, fontSize: 11,
              background: t.purpleSubtle, border: `1px solid ${t.purpleBorder}`,
              color: t.purple, cursor: "pointer", fontWeight: 500,
              opacity: triggerMut.isPending ? 0.6 : 1,
            }}
          >
            <Play size={10} />
            {triggerMut.isPending ? "Running..." : "Run Now"}
          </button>
        </div>
      )}

      {/* Run history */}
      {botId && runsData && runsData.runs.length > 0 && (
        <div style={{ marginTop: 12 }}>
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
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Memory</div>
        <button
          onClick={() => setShowHelp(true)}
          style={{
            background: "none", border: "none", cursor: "pointer",
            color: t.textDim, padding: 2, display: "flex", alignItems: "center",
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
            display: "flex", alignItems: "center", gap: 8, width: "100%",
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
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
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
