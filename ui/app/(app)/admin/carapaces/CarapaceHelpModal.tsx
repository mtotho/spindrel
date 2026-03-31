/**
 * In-depth help modal explaining the carapace system.
 * Uses portal pattern (web-only) consistent with SaveAsTemplateModal.
 */
import { View, Text, Pressable, ScrollView } from "react-native";
import { X } from "lucide-react";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";

interface Props {
  onClose: () => void;
}

export function CarapaceHelpModal({ onClose }: Props) {
  const t = useThemeTokens();

  if (typeof document === "undefined") return null;

  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const ReactDOM = require("react-dom");
  return ReactDOM.createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 10020,
        }}
      />
      {/* Modal */}
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 560,
          maxWidth: "92vw",
          maxHeight: "80vh",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "16px 20px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 15, fontWeight: 700, color: t.text }}>
            Understanding Carapaces
          </span>
          <Pressable onPress={onClose} hitSlop={8}>
            <X size={16} color={t.textDim} />
          </Pressable>
        </div>

        {/* Scrollable body */}
        <div style={{ overflow: "auto", padding: "16px 20px 20px" }}>
          <HelpSection title="What are Carapaces?" t={t}>
            Carapaces are composable expertise bundles that give bots instant domain knowledge.
            Each carapace packages together tools, skills, behavioral instructions, and references
            to other carapaces into a reusable profile. Think of them as "hats" a bot can wear
            — a QA Expert carapace, a Code Reviewer carapace, an Orchestrator carapace.
          </HelpSection>

          <HelpSection title="Composition via Includes" t={t}>
            Carapaces can reference other carapaces through the <Code t={t}>includes</Code> field.
            When applied, all included carapaces are resolved depth-first (max 5 levels, cycle-safe).
            This lets you build complex expertise from simple building blocks.
            For example, a "QA Expert" carapace might include "Code Reviewer" to inherit its
            tools and skills while adding its own QA-specific instructions.
          </HelpSection>

          <HelpSection title="Field Reference" t={t}>
            <FieldDef name="Skills" t={t}>
              Knowledge documents injected into the bot's context.
              Prefix with <Code t={t}>*</Code> for pinned mode (always included every turn).
              Default mode is on_demand (bot fetches via tool when needed).
            </FieldDef>
            <FieldDef name="Local Tools" t={t}>
              Python tools the bot can call — e.g. <Code t={t}>exec_command</Code>,{" "}
              <Code t={t}>file</Code>, <Code t={t}>web_search</Code>. These extend the bot's
              base tool set.
            </FieldDef>
            <FieldDef name="MCP Tools" t={t}>
              External tools from MCP servers — e.g. <Code t={t}>homeassistant</Code>,{" "}
              <Code t={t}>github</Code>. The bot gains access to these servers' tools.
            </FieldDef>
            <FieldDef name="Pinned Tools" t={t}>
              Tools that bypass RAG retrieval — always available regardless of query relevance.
              Use for tools the bot must always have access to.
            </FieldDef>
            <FieldDef name="System Prompt Fragment" t={t}>
              Behavioral instructions injected into the system prompt when active.
              This is the "soul" of the carapace — workflow steps, priorities,
              decision-making guidelines. Write in markdown.
            </FieldDef>
            <FieldDef name="Includes" t={t}>
              Other carapace IDs to compose with. All their tools, skills, and prompt fragments
              merge in during resolution.
            </FieldDef>
            <FieldDef name="Tags" t={t}>
              Organizational labels for filtering and search.
            </FieldDef>
          </HelpSection>

          <HelpSection title="How Carapaces Get Applied" t={t}>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <ApplyMethod label="Bot config" t={t}>
                <Code t={t}>carapaces: [qa, code-review]</Code> in bot YAML — always active for that bot.
              </ApplyMethod>
              <ApplyMethod label="Channel overrides" t={t}>
                <Code t={t}>carapaces_extra</Code> adds and{" "}
                <Code t={t}>carapaces_disabled</Code> removes per-channel.
              </ApplyMethod>
              <ApplyMethod label="Task execution" t={t}>
                Pass carapaces in <Code t={t}>execution_config</Code> for scheduled/deferred tasks.
              </ApplyMethod>
              <ApplyMethod label="Delegation" t={t}>
                Include carapaces when delegating work to another bot.
              </ApplyMethod>
            </div>
          </HelpSection>

          <HelpSection title="Source Types" t={t} last>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span style={{ fontSize: 12, color: t.textMuted }}>
                <Code t={t}>manual</Code> — Created via API/UI, fully editable.
              </span>
              <span style={{ fontSize: 12, color: t.textMuted }}>
                <Code t={t}>file</Code> — Loaded from YAML files on disk, read-only in UI.
              </span>
              <span style={{ fontSize: 12, color: t.textMuted }}>
                <Code t={t}>integration</Code> — Provided by an integration, read-only.
              </span>
            </div>
          </HelpSection>
        </div>
      </div>
    </>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function HelpSection({
  title,
  children,
  t,
  last,
}: {
  title: string;
  children: React.ReactNode;
  t: ThemeTokens;
  last?: boolean;
}) {
  return (
    <div style={{ marginBottom: last ? 0 : 20 }}>
      <div
        style={{
          fontSize: 12,
          fontWeight: 700,
          color: t.accent,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          marginBottom: 6,
        }}
      >
        {title}
      </div>
      <div style={{ fontSize: 13, color: t.textMuted, lineHeight: 1.5 }}>
        {children}
      </div>
    </div>
  );
}

function FieldDef({
  name,
  children,
  t,
}: {
  name: string;
  children: React.ReactNode;
  t: ThemeTokens;
}) {
  return (
    <div style={{ marginBottom: 8 }}>
      <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{name}</span>
      <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2, lineHeight: 1.4 }}>
        {children}
      </div>
    </div>
  );
}

function ApplyMethod({
  label,
  children,
  t,
}: {
  label: string;
  children: React.ReactNode;
  t: ThemeTokens;
}) {
  return (
    <div style={{ fontSize: 12, color: t.textMuted }}>
      <span style={{ fontWeight: 600, color: t.text }}>{label}:</span>{" "}
      {children}
    </div>
  );
}

function Code({ children, t }: { children: React.ReactNode; t: ThemeTokens }) {
  return (
    <span
      style={{
        fontFamily: "monospace",
        fontSize: 11,
        background: t.codeBg,
        border: `1px solid ${t.codeBorder}`,
        borderRadius: 3,
        padding: "1px 4px",
        color: t.codeText,
      }}
    >
      {children}
    </span>
  );
}
