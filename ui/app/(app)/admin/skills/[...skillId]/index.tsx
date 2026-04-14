import { useState, useCallback } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { Trash2, Info } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { DetailHeader } from "@/src/components/layout/DetailHeader";
import { useSkill, useCreateSkill, useUpdateSkill, useDeleteSkill } from "@/src/api/hooks/useSkills";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { FormRow, TextInput, Section } from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function InfoRow({ label, value }: { label: string; value: string }) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 11, color: t.textDim }}>{label}</span>
      <span style={{ fontSize: 11, color: t.text, fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

export default function SkillDetailScreen() {
  const t = useThemeTokens();
  const params = useLocalSearchParams<{ skillId: string | string[] }>();
  const skillId = Array.isArray(params.skillId) ? params.skillId.join("/") : params.skillId;
  const isNew = skillId === "new";
  const goBack = useGoBack("/admin/skills");
  const { data: skill, isLoading } = useSkill(isNew ? undefined : skillId);
  const createMut = useCreateSkill();
  const updateMut = useUpdateSkill(skillId);
  const deleteMut = useDeleteSkill();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  const { width } = useWindowDimensions();
  const isWide = width >= 768;

  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [initialized, setInitialized] = useState(isNew);

  if (skill && !initialized) {
    setName(skill.name || "");
    setContent(skill.content || "");
    setInitialized(true);
  }

  const isFileManaged = skill?.source_type === "file" || skill?.source_type === "integration";

  const handleSave = useCallback(async () => {
    if (isNew) {
      if (!id.trim() || !name.trim()) return;
      await createMut.mutateAsync({ id: id.trim(), name: name.trim(), content });
      goBack();
    } else {
      if (!name.trim()) return;
      await updateMut.mutateAsync({ name: name.trim(), content });
    }
  }, [isNew, id, name, content, createMut, updateMut, goBack]);

  const handleDelete = useCallback(async () => {
    if (!skillId) return;
    const enrolledMsg = skill?.enrolled_bot_count
      ? ` It is enrolled in ${skill.enrolled_bot_count} bot${skill.enrolled_bot_count !== 1 ? "s" : ""}.`
      : "";
    const ok = await confirm(
      `Delete "${skill?.name || skillId}" permanently?${enrolledMsg} This cannot be undone.`,
      { title: "Delete skill", variant: "danger", confirmLabel: "Delete permanently" },
    );
    if (!ok) return;
    await deleteMut.mutateAsync(skillId);
    goBack();
  }, [skillId, skill, deleteMut, goBack, confirm]);

  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = isNew ? (id.trim() && name.trim()) : name.trim();
  const mutError = createMut.error || updateMut.error || deleteMut.error;

  if (!isNew && isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <DetailHeader
        parentLabel="Skills"
        parentHref="/admin/skills"
        title={isNew ? "New Skill" : "Edit Skill"}
        subtitle={!isNew ? skillId : undefined}
        right={
          <>
            {!isNew && !isFileManaged && (
              <button
                onClick={handleDelete}
                disabled={deleteMut.isPending}
                title="Delete"
                style={{
                  display: "flex", alignItems: "center", gap: isWide ? 6 : 0,
                  padding: isWide ? "6px 14px" : "6px 8px", fontSize: 13,
                  border: `1px solid ${t.dangerBorder}`, borderRadius: 6,
                  background: "transparent", color: t.danger, cursor: "pointer", flexShrink: 0,
                }}
              >
                <Trash2 size={14} />
                {isWide && "Delete"}
              </button>
            )}
            <button
              onClick={handleSave}
              disabled={isSaving || !canSave || isFileManaged}
              style={{
                padding: isWide ? "6px 20px" : "6px 12px", fontSize: 13, fontWeight: 600,
                border: "none", borderRadius: 6, flexShrink: 0,
                background: (!canSave || isFileManaged) ? t.surfaceBorder : t.accent,
                color: (!canSave || isFileManaged) ? t.textDim : "#fff",
                cursor: (!canSave || isFileManaged) ? "not-allowed" : "pointer",
              }}
            >
              {isSaving ? "..." : isNew ? "Create & Embed" : "Save & Re-embed"}
            </button>
          </>
        }
      />

      {/* Error display */}
      {mutError && (
        <div style={{ padding: "8px 20px", background: t.dangerSubtle, color: t.danger, fontSize: 12 }}>
          {(mutError as any)?.message || "An error occurred"}
        </div>
      )}

      {/* File-managed banner */}
      {isFileManaged && (
        <div style={{
          margin: isWide ? "16px 20px 0" : "12px 12px 0",
          padding: "12px 16px", borderRadius: 8,
          background: t.accentSubtle, border: `1px solid ${t.accentBorder}`,
          display: "flex", alignItems: "flex-start", gap: 10,
        }}>
          <Info size={14} color={t.accent} style={{ flexShrink: 0, marginTop: 1 }} />
          <div style={{ fontSize: 12, color: t.accent, lineHeight: 1.5 }}>
            This skill is managed by a {skill?.source_type} (
            <code style={{ fontSize: 11, fontWeight: 600 }}>{skill?.source_path}</code>
            ). Edit the source file to make changes &mdash; the server will pick them up automatically.
          </div>
        </div>
      )}

      {/* Body */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        ...(isWide ? { flexDirection: "row", flex: 1 } : {}),
      }}>
        {/* Content editor */}
        <div style={{
          ...(isWide ? { flex: 3, borderRight: `1px solid ${t.surfaceOverlay}` } : {}),
          display: "flex", flexDirection: "column",
          padding: isWide ? "16px 20px" : "12px 12px",
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 6 }}>
            Content (Markdown)
          </div>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            readOnly={isFileManaged}
            placeholder="Write skill content in Markdown. Chunks are split by ## headings."
            style={{
              flex: 1, minHeight: isWide ? 400 : 250,
              background: isFileManaged ? t.surface : t.inputBg,
              border: `1px solid ${isFileManaged ? t.surfaceBorder : t.surfaceOverlay}`, borderRadius: 8,
              padding: 12, fontSize: 13, lineHeight: 1.6,
              color: isFileManaged ? t.textMuted : t.text,
              fontFamily: "monospace", resize: "vertical",
              outline: "none",
            }}
          />
          <div style={{ fontSize: 10, color: t.textDim, marginTop: 6 }}>
            Chunks are split by <code style={{ color: t.textDim }}>## </code> headings and re-embedded on save.
          </div>
        </div>

        {/* Metadata panel */}
        <div style={{
          ...(isWide ? { flex: 1.5, minWidth: 260 } : {}),
          padding: isWide ? "16px 20px" : "12px 12px",
          borderTop: isWide ? "none" : `1px solid ${t.surfaceOverlay}`,
        }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {isNew && (
              <Section title="Identity">
                <FormRow label="Skill ID" description="Lowercase slug, cannot be changed later">
                  <TextInput
                    value={id}
                    onChangeText={setId}
                    placeholder="e.g. arch_linux"
                    style={{ fontFamily: "monospace" }}
                  />
                </FormRow>
                <FormRow label="Display Name">
                  <TextInput value={name} onChangeText={setName} placeholder="e.g. Arch Linux" />
                </FormRow>
              </Section>
            )}

            {!isNew && (
              <Section title="Identity">
                <FormRow label="Display Name">
                  <TextInput
                    value={name}
                    onChangeText={isFileManaged ? () => {} : setName}
                    placeholder="Skill name"
                    style={isFileManaged ? { opacity: 0.5, pointerEvents: "none" } : undefined}
                  />
                </FormRow>
              </Section>
            )}

            {skill && (
              <>
                {skill.description && (
                  <Section title="Description">
                    <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.6 }}>
                      {skill.description}
                    </div>
                  </Section>
                )}
                <Section title="Info">
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <InfoRow label="ID" value={skill.id} />
                    <InfoRow label="Source" value={skill.source_type} />
                    {skill.source_path && <InfoRow label="Path" value={skill.source_path} />}
                    {skill.category && <InfoRow label="Category" value={skill.category} />}
                    <InfoRow label="Chunks" value={String(skill.chunk_count)} />
                    <InfoRow label="Enrolled bots" value={String(skill.enrolled_bot_count)} />
                    <InfoRow label="Created" value={fmtDate(skill.created_at)} />
                    <InfoRow label="Updated" value={fmtDate(skill.updated_at)} />
                  </div>
                </Section>
                {skill.triggers && skill.triggers.length > 0 && (
                  <Section title="Triggers">
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                      {skill.triggers.map((trigger) => (
                        <span key={trigger} style={{
                          padding: "2px 8px", borderRadius: 4, fontSize: 11,
                          background: t.surfaceOverlay, color: t.textMuted,
                        }}>
                          {trigger}
                        </span>
                      ))}
                    </div>
                  </Section>
                )}
              </>
            )}
          </div>
        </div>
      </ScrollView>
      <ConfirmDialogSlot />
    </View>
  );
}
