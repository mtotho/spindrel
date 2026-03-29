import { useState, useCallback } from "react";
import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { ChevronLeft, Trash2, Info } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useQueryClient } from "@tanstack/react-query";
import { useSkill, useCreateSkill, useUpdateSkill, useDeleteSkill } from "@/src/api/hooks/useSkills";
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
  const { skillId } = useLocalSearchParams<{ skillId: string }>();
  const isNew = skillId === "new";
  const goBack = useGoBack("/admin/skills");
  const qc = useQueryClient();
  const { data: skill, isLoading } = useSkill(isNew ? undefined : skillId);
  const createMut = useCreateSkill();
  const updateMut = useUpdateSkill(skillId);
  const deleteMut = useDeleteSkill();

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
      qc.invalidateQueries({ queryKey: ["admin-skills"] });
      goBack();
    } else {
      if (!name.trim()) return;
      await updateMut.mutateAsync({ name: name.trim(), content });
      qc.invalidateQueries({ queryKey: ["admin-skills"] });
    }
  }, [isNew, id, name, content, createMut, updateMut, qc, goBack]);

  const handleDelete = useCallback(async () => {
    if (!skillId || !confirm("Delete this skill?")) return;
    await deleteMut.mutateAsync(skillId);
    qc.invalidateQueries({ queryKey: ["admin-skills"] });
    goBack();
  }, [skillId, deleteMut, qc, goBack]);

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
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center",
        padding: isWide ? "12px 20px" : "10px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`, gap: 8,
      }}>
        <button onClick={goBack} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, flexShrink: 0, width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ChevronLeft size={22} color={t.textMuted} />
        </button>
        <span style={{ color: t.text, fontSize: 14, fontWeight: 700, flexShrink: 0 }}>
          {isNew ? "New Skill" : "Edit Skill"}
        </span>
        {!isNew && isWide && (
          <span style={{ color: t.textDim, fontSize: 11, fontFamily: "monospace" }}>{skillId}</span>
        )}
        <div style={{ flex: 1 }} />
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
      </div>

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
            <code style={{ fontSize: 11, color: t.accentMuted }}>{skill?.source_path}</code>
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
              border: `1px solid ${t.surfaceOverlay}`, borderRadius: 8,
              padding: 12, fontSize: 13, lineHeight: 1.6,
              color: isFileManaged ? t.textDim : t.text,
              fontFamily: "monospace", resize: "vertical",
              outline: "none",
              opacity: isFileManaged ? 0.6 : 1,
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
              <Section title="Info">
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  <InfoRow label="ID" value={skill.id} />
                  <InfoRow label="Source" value={skill.source_type} />
                  {skill.source_path && <InfoRow label="Path" value={skill.source_path} />}
                  <InfoRow label="Chunks" value={String(skill.chunk_count)} />
                  <InfoRow label="Created" value={fmtDate(skill.created_at)} />
                  <InfoRow label="Updated" value={fmtDate(skill.updated_at)} />
                </div>
              </Section>
            )}
          </div>
        </div>
      </ScrollView>
    </View>
  );
}
