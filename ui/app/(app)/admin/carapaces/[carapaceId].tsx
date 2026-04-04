import { useState, useEffect, useCallback } from "react";
import { View, Text, Pressable, ActivityIndicator, Alert, Platform } from "react-native";
import { Link, useLocalSearchParams, useRouter } from "expo-router";
import {
  useCarapace,
  useCreateCarapace,
  useUpdateCarapace,
  useDeleteCarapace,
  useResolveCarapace,
  useCarapaceUsage,
} from "@/src/api/hooks/useCarapaces";
import type { CarapaceUsageItem } from "@/src/api/hooks/useCarapaces";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Save, Trash2, ArrowLeft, ChevronDown, ChevronRight,
  Layers, HelpCircle, Info, Bot, Hash, Home, Zap,
} from "lucide-react";
import { CarapaceHelpModal } from "./CarapaceHelpModal";
import { Section, FormRow } from "@/src/components/shared/FormControls";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import type { Carapace, SkillConfig } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CarapaceDetailPage() {
  const t = useThemeTokens();
  const router = useRouter();
  const { carapaceId } = useLocalSearchParams<{ carapaceId: string }>();
  const isNew = carapaceId === "new";

  const { data: existing, isLoading } = useCarapace(isNew ? undefined : carapaceId);
  const { data: resolved } = useResolveCarapace(isNew ? undefined : carapaceId);
  const { data: usage } = useCarapaceUsage(isNew ? undefined : carapaceId);
  const createMut = useCreateCarapace();
  const updateMut = useUpdateCarapace(carapaceId || "");
  const deleteMut = useDeleteCarapace();

  const [draft, setDraft] = useState<Partial<Carapace>>({
    id: "",
    name: "",
    description: "",
    skills: [],
    local_tools: [],
    mcp_tools: [],
    pinned_tools: [],
    system_prompt_fragment: "",
    includes: [],
    tags: [],
  });
  const [dirty, setDirty] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    if (existing && !isNew) {
      setDraft({
        id: existing.id,
        name: existing.name,
        description: existing.description || "",
        skills: existing.skills || [],
        local_tools: existing.local_tools || [],
        mcp_tools: existing.mcp_tools || [],
        pinned_tools: existing.pinned_tools || [],
        system_prompt_fragment: existing.system_prompt_fragment || "",
        includes: existing.includes || [],
        tags: existing.tags || [],
      });
    }
  }, [existing, isNew]);

  const update = useCallback((patch: Partial<Carapace>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
    setDirty(true);
  }, []);

  const handleSave = async () => {
    try {
      if (isNew) {
        await createMut.mutateAsync({
          id: draft.id || "",
          name: draft.name || "",
          description: draft.description || undefined,
          skills: draft.skills || [],
          local_tools: draft.local_tools || [],
          mcp_tools: draft.mcp_tools || [],
          pinned_tools: draft.pinned_tools || [],
          system_prompt_fragment: draft.system_prompt_fragment || undefined,
          includes: draft.includes || [],
          tags: draft.tags || [],
        });
        router.back();
      } else {
        await updateMut.mutateAsync({
          name: draft.name,
          description: draft.description || undefined,
          skills: draft.skills,
          local_tools: draft.local_tools,
          mcp_tools: draft.mcp_tools,
          pinned_tools: draft.pinned_tools,
          system_prompt_fragment: draft.system_prompt_fragment || undefined,
          includes: draft.includes,
          tags: draft.tags,
        });
        setDirty(false);
      }
    } catch {
      // error handled by mutation
    }
  };

  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const handleDelete = () => {
    setShowDeleteConfirm(true);
  };

  const doDelete = async () => {
    setShowDeleteConfirm(false);
    try {
      await deleteMut.mutateAsync(carapaceId!);
      router.back();
    } catch {
      // error shown via mutation state
    }
  };

  const isFileBased =
    existing?.source_type === "file" || existing?.source_type === "integration";

  if (!isNew && isLoading) {
    return <ActivityIndicator style={{ marginTop: 60 }} />;
  }

  const hasIncludes = (draft.includes || []).length > 0;
  const inputStyle = makeInputStyle(t, isFileBased);
  const textareaStyle = makeTextareaStyle(t, isFileBased);

  return (
    <div style={{ overflow: "auto", flex: 1, background: t.surface }}>
      <MobileHeader title={isNew ? "New Carapace" : draft.name || "Carapace"} />
      <div style={{ padding: 16, maxWidth: 720 }}>
        {/* Top actions */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 16,
          }}
        >
          <Pressable
            onPress={() => router.back()}
            style={{ flexDirection: "row", alignItems: "center", gap: 6 }}
          >
            <ArrowLeft size={16} color={t.textMuted} />
            <Text style={{ color: t.textMuted, fontSize: 13 }}>Back</Text>
          </Pressable>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              onClick={() => setShowHelp(true)}
              title="Help — what are carapaces?"
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: 4,
                display: "flex",
                alignItems: "center",
              }}
            >
              <HelpCircle size={16} color={t.textDim} />
            </button>
            {!isNew && !isFileBased && (
              <Pressable
                onPress={handleDelete}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  paddingHorizontal: 10,
                  paddingVertical: 6,
                  borderRadius: 6,
                  backgroundColor: t.dangerSubtle,
                  borderWidth: 1,
                  borderColor: t.dangerBorder,
                }}
              >
                <Trash2 size={14} color={t.danger} />
                <Text style={{ color: t.danger, fontSize: 12 }}>Delete</Text>
              </Pressable>
            )}
            {!isFileBased && (
              <Pressable
                onPress={handleSave}
                disabled={!dirty && !isNew}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 4,
                  paddingHorizontal: 12,
                  paddingVertical: 6,
                  borderRadius: 6,
                  backgroundColor: dirty || isNew ? t.accent : t.surfaceBorder,
                  opacity: dirty || isNew ? 1 : 0.5,
                }}
              >
                <Save size={14} color="#fff" />
                <Text style={{ color: "#fff", fontSize: 12, fontWeight: "600" }}>
                  {isNew ? "Create" : "Save"}
                </Text>
              </Pressable>
            )}
          </div>
        </div>

        {/* Error banner */}
        {(createMut.isError || updateMut.isError || deleteMut.isError) && (
          <div
            style={{
              background: t.dangerSubtle,
              border: `1px solid ${t.dangerBorder}`,
              padding: 10,
              borderRadius: 8,
              marginBottom: 12,
              color: t.danger,
              fontSize: 12,
            }}
          >
            {(createMut.error || updateMut.error || deleteMut.error)?.message ||
              "Operation failed"}
          </div>
        )}

        {/* File-managed banner */}
        {isFileBased && (
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 8,
              background: t.accentSubtle,
              border: `1px solid ${t.accentBorder}`,
              padding: 10,
              borderRadius: 8,
              marginBottom: 16,
              color: t.accent,
              fontSize: 12,
            }}
          >
            <Info size={14} color={t.accent} style={{ flexShrink: 0, marginTop: 1 } as any} />
            <span>
              This carapace is managed by a {existing?.source_type} ({existing?.source_path}).
              Edit the source to make changes.
            </span>
          </div>
        )}

        {/* ─── Identity ─────────────────────────────────── */}
        <Section title="Identity" description="Name, description, and organizational tags">
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {isNew && (
              <FormRow label="ID" description="Unique slug identifier (lowercase, hyphens). Cannot be changed after creation.">
                <input
                  value={draft.id || ""}
                  onChange={(e) =>
                    update({ id: e.target.value.toLowerCase().replace(/\s+/g, "-") })
                  }
                  placeholder="e.g. qa-expert"
                  style={inputStyle}
                  onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                  onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
                />
              </FormRow>
            )}

            <FormRow label="Name" description="Display name shown in the UI and bot config.">
              <input
                value={draft.name || ""}
                onChange={(e) => update({ name: e.target.value })}
                placeholder="e.g. QA Expert"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
            </FormRow>

            <FormRow label="Description" description="Brief summary of what this carapace provides.">
              <input
                value={draft.description || ""}
                onChange={(e) => update({ description: e.target.value })}
                placeholder="e.g. Full QA workflow — test planning, execution, and reporting"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
            </FormRow>

            <FormRow label="Tags" description="Comma-separated labels for filtering and search.">
              <input
                value={(draft.tags || []).join(", ")}
                onChange={(e) =>
                  update({
                    tags: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="e.g. testing, quality"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <TagPreview items={draft.tags || []} t={t} color="purple" />
            </FormRow>
          </div>
        </Section>

        {/* ─── Capabilities ─────────────────────────────── */}
        <Section
          title="Capabilities"
          description="Tools and skills the bot gains when this carapace is active"
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <FormRow
              label="Skills"
              description="Comma-separated skill IDs. Prefix with * for pinned mode (always injected). Default is on_demand (bot fetches when needed)."
            >
              <input
                value={skillsToString(draft.skills || [])}
                onChange={(e) => update({ skills: parseSkillsString(e.target.value) })}
                placeholder="e.g. *workspace-orchestrator, channel-workspace"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <SkillPreview skills={draft.skills || []} t={t} />
            </FormRow>

            <FormRow
              label="Local Tools"
              description="Python tools added to the bot's toolbox — e.g. exec_command, file, web_search."
            >
              <input
                value={(draft.local_tools || []).join(", ")}
                onChange={(e) =>
                  update({
                    local_tools: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="e.g. exec_command, file, web_search"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <TagPreview items={draft.local_tools || []} t={t} color="success" />
            </FormRow>

            <FormRow
              label="Pinned Tools"
              description="Tools that bypass RAG retrieval — always available regardless of query relevance."
            >
              <input
                value={(draft.pinned_tools || []).join(", ")}
                onChange={(e) =>
                  update({
                    pinned_tools: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="e.g. exec_command"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <TagPreview items={draft.pinned_tools || []} t={t} color="warning" />
            </FormRow>

            <FormRow
              label="MCP Servers"
              description="External MCP server names — the bot gains access to all tools from these servers."
            >
              <input
                value={(draft.mcp_tools || []).join(", ")}
                onChange={(e) =>
                  update({
                    mcp_tools: e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                  })
                }
                placeholder="e.g. homeassistant, github"
                disabled={isFileBased}
                style={inputStyle}
                onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
                onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
              />
              <TagPreview items={draft.mcp_tools || []} t={t} color="accent" />
            </FormRow>
          </div>
        </Section>

        {/* ─── Behavior ─────────────────────────────────── */}
        <Section
          title="Behavior"
          description="System prompt fragment — the 'soul' of this carapace"
        >
          <FormRow
            label="System Prompt Fragment"
            description="Markdown-formatted instructions injected into the system prompt. Define workflow steps, priorities, constraints, and decision-making guidelines."
          >
            <textarea
              value={draft.system_prompt_fragment || ""}
              onChange={(e) => update({ system_prompt_fragment: e.target.value })}
              placeholder={"## Expert Mode\n\nWhen activated, follow this workflow:\n1. Assess the situation\n2. Plan your approach\n3. Execute with precision"}
              disabled={isFileBased}
              rows={8}
              style={textareaStyle}
              onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
              onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
            />
            {(draft.system_prompt_fragment || "").length > 0 && (
              <div style={{ fontSize: 10, color: t.textDim, textAlign: "right" }}>
                {draft.system_prompt_fragment!.length} chars
              </div>
            )}
          </FormRow>
        </Section>

        {/* ─── Composition ──────────────────────────────── */}
        <Section
          title="Composition"
          description="Include other carapaces to inherit their tools, skills, and fragments"
        >
          <FormRow
            label="Includes"
            description="Comma-separated carapace IDs. Resolved depth-first (max 5 levels, cycle-safe). All tools, skills, and prompt fragments merge in."
          >
            <input
              value={(draft.includes || []).join(", ")}
              onChange={(e) =>
                update({
                  includes: e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              placeholder="e.g. code-review, testing"
              disabled={isFileBased}
              style={inputStyle}
              onFocus={(e) => { e.target.style.borderColor = t.inputBorderFocus; }}
              onBlur={(e) => { e.target.style.borderColor = t.inputBorder; }}
            />
            <TagPreview items={draft.includes || []} t={t} color="accent" />
          </FormRow>
        </Section>

        {/* ─── Used By ─────────────────────────────────── */}
        {!isNew && usage && usage.length > 0 && (
          <Section title="Used By" description="Bots and channels that reference this carapace">
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {usage.map((item, i) => (
                <UsageRow key={`${item.type}-${item.id}-${i}`} item={item} t={t} />
              ))}
            </div>
          </Section>
        )}

        {/* ─── Resolved Preview ─────────────────────────── */}
        {!isNew && resolved && (hasIncludes || resolved.local_tools.length > 0) && (
          <div style={{ marginTop: 16 }}>
            <button
              onClick={() => setShowResolved(!showResolved)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "8px 0",
                background: "none",
                border: "none",
                cursor: "pointer",
                color: t.text,
              }}
            >
              {showResolved ? (
                <ChevronDown size={14} color={t.textMuted} />
              ) : (
                <ChevronRight size={14} color={t.textMuted} />
              )}
              <Layers size={14} color={t.accent} />
              <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                Resolved Preview
              </span>
              {hasIncludes && (
                <span style={{ fontSize: 11, color: t.textDim }}>
                  ({resolved.resolved_ids.length} carapace
                  {resolved.resolved_ids.length !== 1 ? "s" : ""})
                </span>
              )}
            </button>

            {showResolved && (
              <div
                style={{
                  background: t.surface,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 8,
                  padding: 14,
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                }}
              >
                {resolved.resolved_ids.length > 1 && (
                  <ResolvedRow label="Includes chain" t={t}>
                    <span
                      style={{
                        fontSize: 11,
                        color: t.textMuted,
                        fontFamily: "monospace",
                      }}
                    >
                      {resolved.resolved_ids.join(" → ")}
                    </span>
                  </ResolvedRow>
                )}
                <ResolvedRow label="Tools" t={t}>
                  <TagPreview items={resolved.local_tools} t={t} color="success" />
                </ResolvedRow>
                {resolved.mcp_tools.length > 0 && (
                  <ResolvedRow label="MCP" t={t}>
                    <TagPreview items={resolved.mcp_tools} t={t} color="accent" />
                  </ResolvedRow>
                )}
                <ResolvedRow label="Pinned" t={t}>
                  <TagPreview items={resolved.pinned_tools} t={t} color="warning" />
                </ResolvedRow>
                <ResolvedRow label="Skills" t={t}>
                  <SkillPreview skills={resolved.skills} t={t} />
                </ResolvedRow>
                <ResolvedRow label="Fragments" t={t}>
                  <span style={{ fontSize: 11, color: t.textMuted }}>
                    {resolved.system_prompt_fragments.length} fragment
                    {resolved.system_prompt_fragments.length !== 1 ? "s" : ""},{" "}
                    {resolved.system_prompt_fragments.reduce(
                      (a, f) => a + f.length,
                      0,
                    )}{" "}
                    chars
                  </span>
                </ResolvedRow>
              </div>
            )}
          </div>
        )}
      </div>

      {showHelp && <CarapaceHelpModal onClose={() => setShowHelp(false)} />}
      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete Carapace"
        message={`Delete carapace "${draft.name}"? This cannot be undone.`}
        confirmLabel="Delete"
        variant="danger"
        onConfirm={doDelete}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function UsageRow({ item, t }: { item: CarapaceUsageItem; t: ThemeTokens }) {
  const Icon = item.type === "bot" ? Bot : item.auto_injected ? Home : Hash;
  const label = item.type === "bot" ? "Bot" : "Channel";
  const href = item.type === "bot"
    ? `/admin/bots/${item.id}`
    : `/channels/${item.id}`;

  return (
    <Link href={href as any} asChild>
      <Pressable
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: 8,
          padding: 8,
          borderRadius: 6,
          backgroundColor: t.surface,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
        }}
      >
        <Icon size={14} color={item.auto_injected ? t.accent : t.textDim} />
        <Text style={{ fontSize: 13, color: t.text, flex: 1 }} numberOfLines={1}>
          {item.name || item.id}
        </Text>
        <Text style={{ fontSize: 11, color: t.textDim }}>{label}</Text>
        {item.auto_injected && (
          <View style={{
            flexDirection: "row",
            alignItems: "center",
            gap: 3,
            backgroundColor: t.accentSubtle,
            borderWidth: 1,
            borderColor: t.accentBorder,
            paddingHorizontal: 5,
            paddingVertical: 1,
            borderRadius: 4,
          }}>
            <Zap size={9} color={t.accent} />
            <Text style={{ fontSize: 10, color: t.accent }}>auto-injected</Text>
          </View>
        )}
        {item.type === "channel_inherited" && (
          <Text style={{ fontSize: 10, color: t.textDim }}>via bot</Text>
        )}
      </Pressable>
    </Link>
  );
}

function ResolvedRow({
  label,
  t,
  children,
}: {
  label: string;
  t: ThemeTokens;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: t.textDim }}>{label}</span>
      {children}
    </div>
  );
}

type TagColor = "purple" | "accent" | "success" | "warning";

function TagPreview({
  items,
  t,
  color,
}: {
  items: string[];
  t: ThemeTokens;
  color: TagColor;
}) {
  if (items.length === 0) return null;
  const colorMap: Record<TagColor, { bg: string; border: string; text: string }> = {
    purple: { bg: t.purpleSubtle, border: t.purpleBorder, text: t.purple },
    accent: { bg: t.accentSubtle, border: t.accentBorder, text: t.accent },
    success: { bg: t.successSubtle, border: t.successBorder, text: t.success },
    warning: { bg: t.warningSubtle, border: t.warningBorder, text: t.warning },
  };
  const c = colorMap[color];
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
      {items.map((item) => (
        <span
          key={item}
          style={{
            fontSize: 11,
            color: c.text,
            background: c.bg,
            border: `1px solid ${c.border}`,
            borderRadius: 4,
            padding: "1px 6px",
          }}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

function SkillPreview({ skills, t }: { skills: SkillConfig[]; t: ThemeTokens }) {
  if (skills.length === 0) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
      {skills.map((s) => {
        const isPinned = s.mode === "pinned";
        return (
          <span
            key={s.id}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              fontSize: 11,
              color: isPinned ? t.accent : t.purple,
              background: isPinned ? t.accentSubtle : t.purpleSubtle,
              border: `1px solid ${isPinned ? t.accentBorder : t.purpleBorder}`,
              borderRadius: 4,
              padding: "1px 6px",
            }}
          >
            {s.id}
            <span style={{ fontSize: 9, color: t.textDim }}>{s.mode || "on_demand"}</span>
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

function makeInputStyle(
  t: ThemeTokens,
  disabled?: boolean,
): React.CSSProperties {
  return {
    background: t.inputBg,
    border: `1px solid ${t.inputBorder}`,
    borderRadius: 8,
    padding: "8px 12px",
    color: t.inputText,
    fontSize: 14,
    width: "100%",
    outline: "none",
    transition: "border-color 0.15s",
    opacity: disabled ? 0.6 : 1,
    cursor: disabled ? "not-allowed" : undefined,
  };
}

function makeTextareaStyle(
  t: ThemeTokens,
  disabled?: boolean,
): React.CSSProperties {
  return {
    ...makeInputStyle(t, disabled),
    resize: "vertical" as const,
    fontFamily: "monospace",
    fontSize: 13,
    lineHeight: 1.5,
  };
}

// ---------------------------------------------------------------------------
// Skill string parsing
// ---------------------------------------------------------------------------

function skillsToString(skills: SkillConfig[]): string {
  return skills
    .map((s) => (s.mode === "pinned" ? `*${s.id}` : s.id))
    .join(", ");
}

function parseSkillsString(input: string): SkillConfig[] {
  return input
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => {
      if (s.startsWith("*")) {
        return { id: s.slice(1), mode: "pinned" };
      }
      return { id: s, mode: "on_demand" };
    });
}
