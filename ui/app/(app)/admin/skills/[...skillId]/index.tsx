import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Bot, Code2, FileText, Info, Save, Trash2 } from "lucide-react";

import { useCreateSkill, useDeleteSkill, useSkill, useSkills, useUpdateSkill } from "@/src/api/hooks/useSkills";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useGoBack } from "@/src/hooks/useGoBack";
import { useUIStore } from "@/src/stores/ui";
import { buildRecentHref } from "@/src/lib/recentPages";
import { FormRow, Section, TextInput } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSegmentedControl,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import { SourceTextEditor } from "@/src/components/shared/SourceTextEditor";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";

import { analyzeSkill, skillSourceBucket, skillSourceLabel, splitSkillContent } from "../skillLibrary";

type ViewMode = "preview" | "source";
type BadgeVariant = "success" | "warning" | "danger" | "info" | "neutral" | "purple" | "skipped";

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sourceVariant(bucket: ReturnType<typeof skillSourceBucket>): BadgeVariant {
  if (bucket === "integration") return "warning";
  if (bucket === "bot") return "purple";
  if (bucket === "manual") return "neutral";
  return "info";
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-start justify-between gap-3 text-[12px]">
      <span className="shrink-0 text-text-dim">{label}</span>
      <span className="min-w-0 text-right font-mono text-text-muted break-all">{value}</span>
    </div>
  );
}

export default function SkillDetailScreen() {
  const { "*": skillId } = useParams();
  const isNew = skillId === "new";
  const navigate = useNavigate();
  const goBack = useGoBack("/admin/skills");
  const { data: skill, isLoading } = useSkill(isNew ? undefined : skillId);
  const { data: allSkills = [] } = useSkills();
  const createMut = useCreateSkill();
  const updateMut = useUpdateSkill(skillId);
  const deleteMut = useDeleteSkill();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [mode, setMode] = useState<ViewMode>("preview");

  const enrichRecentPage = useUIStore((s) => s.enrichRecentPage);
  const loc = useLocation();
  useEffect(() => {
    if (skill?.name) enrichRecentPage(buildRecentHref(loc.pathname, loc.search, loc.hash), skill.name);
  }, [skill?.name, loc.pathname, loc.search, loc.hash, enrichRecentPage]);

  useEffect(() => {
    if (!skill || isNew) return;
    setName(skill.name || "");
    setContent(skill.content || "");
  }, [isNew, skill]);

  const readOnly = Boolean(skill?.source_type === "file" || skill?.source_type === "integration");
  const isSaving = createMut.isPending || updateMut.isPending;
  const canSave = isNew ? Boolean(id.trim() && name.trim()) : Boolean(name.trim() && !readOnly);
  const mutError = createMut.error || updateMut.error || deleteMut.error;
  const analysis = useMemo(() => (
    skill ? analyzeSkill({ ...skill, content }) : splitSkillContent(content)
  ), [content, skill]);
  const sourceBucket = skill ? skillSourceBucket(skill) : "manual";
  const childSkills = useMemo(
    () => (skill ? allSkills.filter((item) => item.folder_root_id === skill.id || item.parent_skill_id === skill.id) : []),
    [allSkills, skill],
  );

  const handleSave = useCallback(async () => {
    if (isNew) {
      if (!id.trim() || !name.trim()) return;
      await createMut.mutateAsync({ id: id.trim(), name: name.trim(), content });
      goBack();
      return;
    }
    if (!name.trim() || readOnly) return;
    await updateMut.mutateAsync({ name: name.trim(), content });
  }, [content, createMut, goBack, id, isNew, name, readOnly, updateMut]);

  const handleDelete = useCallback(async () => {
    if (!skillId || !skill) return;
    const enrolledMsg = skill.enrolled_bot_count
      ? ` It is enrolled in ${skill.enrolled_bot_count} bot${skill.enrolled_bot_count === 1 ? "" : "s"}.`
      : "";
    const ok = await confirm(
      `Delete "${skill.name || skillId}" permanently?${enrolledMsg} This cannot be undone.`,
      { title: "Delete skill", variant: "danger", confirmLabel: "Delete permanently" },
    );
    if (!ok) return;
    await deleteMut.mutateAsync(skillId);
    goBack();
  }, [confirm, deleteMut, goBack, skill, skillId]);

  if (!isNew && isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Skills"
        backTo="/admin/skills"
        title={isNew ? "New Skill" : skill?.name || "Skill"}
        subtitle={!isNew ? skillId : "Manual library entry"}
        right={
          <div className="flex items-center gap-1.5">
            {!isNew && skill && <StatusBadge label={readOnly ? "read only" : "editable"} variant={readOnly ? "neutral" : "info"} />}
            {!isNew && skill && !readOnly && (
              <ActionButton
                label="Delete"
                variant="danger"
                icon={<Trash2 size={14} />}
                disabled={deleteMut.isPending}
                onPress={handleDelete}
              />
            )}
            <ActionButton
              label={isNew ? "Create & Embed" : "Save & Re-embed"}
              icon={<Save size={14} />}
              disabled={isSaving || !canSave}
              onPress={handleSave}
            />
          </div>
        }
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1280px] flex-col gap-7 p-6">
          {mutError && (
            <InfoBanner variant="danger" icon={<AlertTriangle size={13} />}>
              {(mutError as Error)?.message || "Skill update failed."}
            </InfoBanner>
          )}

          {readOnly && skill && (
            <InfoBanner variant="info" icon={<Info size={13} />}>
              This skill is managed by {skill.source_type === "integration" ? "an integration package" : "a source file"}.
              {skill.source_path ? <span className="font-mono"> {skill.source_path}</span> : null}
            </InfoBanner>
          )}

          <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col gap-7">
              <Section
                title="Readable Skill"
                description="Preview the instruction body first; inspect the literal Markdown source when needed."
                action={
                  <SettingsSegmentedControl<ViewMode>
                    value={mode}
                    onChange={setMode}
                    options={[
                      { value: "preview", label: "Preview", icon: <FileText size={13} /> },
                      { value: "source", label: "Source", icon: <Code2 size={13} /> },
                    ]}
                  />
                }
              >
                {mode === "preview" ? (
                  analysis.body.trim() ? (
                    <div className="rounded-md bg-surface-raised/35">
                      <MarkdownViewer content={analysis.body} />
                    </div>
                  ) : (
                    <EmptyState message="No readable Markdown body is available yet." />
                  )
                ) : (
                  <SourceTextEditor
                    value={content}
                    onChange={readOnly ? undefined : setContent}
                    language="markdown"
                    readOnly={readOnly}
                    minHeight={520}
                    status={analysis.parseError ? { variant: "danger", label: "Frontmatter error" } : null}
                    placeholder="Write the skill in Markdown. Optional YAML frontmatter goes between --- fences."
                  />
                )}
              </Section>

              {isNew || !readOnly ? (
                <Section title="Identity" description="Manual skills keep the existing edit and re-embed behavior.">
                  <div className="grid gap-4 md:grid-cols-2">
                    {isNew && (
                      <FormRow label="Skill ID" description="Lowercase slug. This cannot be changed later.">
                        <TextInput value={id} onChangeText={setId} placeholder="workspace/release_notes" />
                      </FormRow>
                    )}
                    <FormRow label="Display name">
                      <TextInput value={name} onChangeText={setName} placeholder="Release Notes" />
                    </FormRow>
                  </div>
                </Section>
              ) : null}

              {childSkills.length > 0 && (
                <Section title="Children" description="Folder-layout skills are shown as source groups in the library.">
                  <div className="flex flex-col gap-1.5">
                    {childSkills.map((child) => (
                      <SettingsControlRow
                        key={child.id}
                        leading={<FileText size={14} />}
                        title={child.name || child.id}
                        description={child.description || child.id}
                        meta={<QuietPill label={child.id} maxWidthClass="max-w-[220px]" />}
                        onClick={() => navigate(`/admin/skills/${encodeURIComponent(child.id)}`)}
                      />
                    ))}
                  </div>
                </Section>
              )}
            </div>

            <aside className="flex min-w-0 flex-col gap-6">
              {skill && (
                <Section title="Overview">
                  <div className="flex flex-col gap-3">
                    <SettingsControlRow
                      leading={sourceBucket === "bot" ? <Bot size={14} /> : <FileText size={14} />}
                      title={skillSourceLabel(skill)}
                      description={skill.source_path || skill.id}
                      meta={<StatusBadge label={sourceBucket} variant={sourceVariant(sourceBucket)} />}
                    />
                    <div className="flex flex-col gap-2 rounded-md bg-surface-raised/35 px-3 py-3">
                      <InfoRow label="ID" value={skill.id} />
                      <InfoRow label="Layout" value={skill.skill_layout} />
                      <InfoRow label="Category" value={skill.category || "-"} />
                      <InfoRow label="Chunks" value={skill.chunk_count} />
                      <InfoRow label="Enrolled bots" value={skill.enrolled_bot_count} />
                      <InfoRow label="Surfaced" value={skill.surface_count} />
                      <InfoRow label="Auto-injects" value={skill.total_auto_injects ?? 0} />
                      <InfoRow label="Updated" value={fmtDate(skill.updated_at)} />
                      <InfoRow label="Created" value={fmtDate(skill.created_at)} />
                    </div>
                  </div>
                </Section>
              )}

              <Section title="Frontmatter Quality">
                {analysis.warnings.length ? (
                  <div className="flex flex-col gap-2">
                    {analysis.warnings.map((warning) => (
                      <SettingsControlRow
                        key={warning}
                        compact
                        leading={<AlertTriangle size={13} />}
                        title={warning}
                        description="Advisory only. The skill remains available."
                      />
                    ))}
                  </div>
                ) : (
                  <SettingsControlRow leading={<FileText size={14} />} title="Required metadata present" />
                )}
              </Section>

              {skill?.triggers?.length ? (
                <Section title="Triggers">
                  <div className="flex flex-wrap gap-1.5">
                    {skill.triggers.map((trigger) => <QuietPill key={trigger} label={trigger} maxWidthClass="max-w-[220px]" />)}
                  </div>
                </Section>
              ) : null}

              {skill?.scripts?.length ? (
                <Section title="Scripts" description="Read-only summaries. Script bodies are not exposed here.">
                  <div className="flex flex-col gap-1.5">
                    {skill.scripts.map((script) => (
                      <SettingsControlRow
                        key={script.name}
                        leading={<Code2 size={14} />}
                        title={script.name}
                        description={script.description || "No script description provided."}
                        meta={script.timeout_s ? <QuietPill label={`${script.timeout_s}s`} /> : undefined}
                      />
                    ))}
                  </div>
                </Section>
              ) : null}

              {analysis.frontmatterRaw && (
                <Section title="Frontmatter Source">
                  <SourceTextEditor
                    value={analysis.frontmatterRaw}
                    language="yaml"
                    readOnly
                    minHeight={180}
                    maxHeight={360}
                    status={analysis.parseError ? { variant: "danger", label: "Invalid YAML" } : null}
                  />
                </Section>
              )}
            </aside>
          </div>
        </div>
      </div>
      <ConfirmDialogSlot />
    </div>
  );
}
