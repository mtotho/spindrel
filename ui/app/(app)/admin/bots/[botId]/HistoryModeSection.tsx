/**
 * History mode selector + presets display for the bot editor.
 * Shows auto-injected features and built-in prompt when file mode is active.
 */
import { useState } from "react";
import { Check, ChevronDown } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { SelectInput, FormRow } from "@/src/components/shared/FormControls";
import type { BotConfig } from "@/src/types/api";
import {
  HISTORY_MODE_META,
  getHistoryModeMeta,
  historyModeOptionLabel,
} from "@/src/lib/historyModeMeta";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const FILE_MODE_PRESETS = [
  { label: "read_conversation_history auto-injected", detail: "Tool for navigating archived sections, searching, and retrieving content" },
  { label: "Section index injected every turn", detail: "Numbered list of archived sections with titles, dates, tags, and summaries" },
  { label: "search: query mode", detail: "Search the current session's archived messages for exact strings, errors, ports, and paths" },
  { label: "tool: retrieval mode", detail: "Retrieve full output of summarized tool calls by ID" },
  { label: "Depth-aware compaction", detail: "Early sections preserve detail; later sections become more abstract automatically" },
  { label: "3-tier fallback escalation", detail: "Normal → aggressive → deterministic fallback if LLM fails during compaction" },
];

const FILE_MODE_BUILT_IN_PROMPT = `Archived conversation history — use read_conversation_history with:
  - A section number (e.g. '3') to read a full transcript
  - 'search:<query>' to find matching sections and raw message content in the current session
  - 'tool:<id>' to retrieve full output of a summarized tool call

Section Index (injected each turn):
  §1  Setting Up Slack  [2026-03-25]  #slack #integration
      User configured Slack integration with socket mode.
  §2  Rate Limit Fixes  [2026-03-26]  #debugging #api
      Fixed rate limiting on outbound API calls.
  ...

The section index is rebuilt after each compaction cycle. Older sections are
summarized more aggressively (depth-aware tiers). Use 'search:' mode to
search the current session for exact strings that may have been abstracted away
in summaries, and inspect adjacent sessions separately when needed.`;

// ---------------------------------------------------------------------------
// History Mode Section
// ---------------------------------------------------------------------------
export function HistoryModeSection({ draft, update }: {
  draft: BotConfig;
  update: (p: Partial<BotConfig>) => void;
}) {
  const t = useThemeTokens();
  const mode = getHistoryModeMeta(draft.history_mode || "file");
  const showPresets = !!mode.showFileArtifacts;
  const [showPrompt, setShowPrompt] = useState(false);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <FormRow label="History Mode">
        <SelectInput value={draft.history_mode || "file"} onChange={(v) => update({ history_mode: v })}
          options={HISTORY_MODE_META.map((entry) => ({
            label: historyModeOptionLabel(entry),
            value: entry.value,
          }))}
        />
      </FormRow>

      <div style={{
        background: mode.recommended ? t.successSubtle : t.surface,
        border: `1px solid ${mode.recommended ? `${t.success}22` : t.surfaceRaised}`,
        borderRadius: 8,
        padding: "12px 14px",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: mode.accentColor }}>
            {mode.label}
          </span>
          <span style={{ fontSize: 12, color: t.text }}>{mode.summary}</span>
        </div>
        <div style={{ fontSize: 12, lineHeight: "1.6", color: t.textDim }}>
          {mode.detail}
        </div>
      </div>

      {showPresets && (
        <>
          {/* Presets info */}
          <div style={{
            background: t.successSubtle, border: `1px solid ${t.success}22`,
            borderRadius: 8, padding: "14px 16px",
          }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: t.success, marginBottom: 10 }}>
              File mode — applying presets
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {FILE_MODE_PRESETS.map((p, i) => (
                <div key={i} style={{ display: "flex", flexDirection: "row", alignItems: "flex-start", gap: 8 }}>
                  <Check size={12} color={t.success} style={{ marginTop: 2, flexShrink: 0 } as any} />
                  <div>
                    <span style={{ fontSize: 12, color: t.text }}>{p.label}</span>
                    <span style={{ fontSize: 11, color: t.textDim }}> — {p.detail}</span>
                  </div>
                </div>
              ))}
            </div>
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
              <span style={{ fontSize: 12, fontWeight: 600 }}>Built-in Context (section index + tool)</span>
              <span style={{
                fontSize: 9, padding: "2px 6px", borderRadius: 3,
                background: t.successSubtle, color: t.success,
                marginLeft: 4,
              }}>auto-injected</span>
            </button>
            {showPrompt && (
              <div style={{ padding: "0 16px 14px 16px" }}>
                <pre style={{
                  margin: 0, fontSize: 11, lineHeight: 1.7, color: t.textMuted,
                  fontFamily: "monospace", whiteSpace: "pre-wrap",
                  background: t.inputBg, borderRadius: 6, padding: 12,
                }}>{FILE_MODE_BUILT_IN_PROMPT}</pre>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
