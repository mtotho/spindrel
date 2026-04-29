import { FolderKanban, Layers, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useCreateProject,
  useCreateProjectBlueprint,
  useCreateProjectFromBlueprint,
  useProjectBlueprints,
  useProjects,
} from "@/src/api/hooks/useProjects";
import { useWorkspaces } from "@/src/api/hooks/useWorkspaces";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { FormRow, Section, SelectInput, TextInput } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";

export default function ProjectsIndex() {
  const navigate = useNavigate();
  const { data: projects, isLoading } = useProjects();
  const { data: blueprints } = useProjectBlueprints();
  const { data: workspaces } = useWorkspaces();
  const createProject = useCreateProject();
  const createFromBlueprint = useCreateProjectFromBlueprint();
  const createBlueprint = useCreateProjectBlueprint();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [rootPath, setRootPath] = useState("common/projects");
  const [selectedBlueprintId, setSelectedBlueprintId] = useState("");
  const [blueprintName, setBlueprintName] = useState("");
  const [blueprintRootPattern, setBlueprintRootPattern] = useState("common/projects/{slug}");
  const [blueprintFolders, setBlueprintFolders] = useState(".spindrel,.spindrel/knowledge-base");
  const [blueprintSecrets, setBlueprintSecrets] = useState("");
  const defaultWorkspaceId = workspaces?.[0]?.id;

  const attachedCount = useMemo(
    () => (projects ?? []).reduce((total, project) => total + (project.attached_channel_count ?? 0), 0),
    [projects],
  );
  const blueprintOptions = useMemo(
    () => [
      { label: "No blueprint", value: "" },
      ...(blueprints ?? []).map((blueprint) => ({
        label: blueprint.name,
        value: blueprint.id,
      })),
    ],
    [blueprints],
  );

  const splitList = (value: string) =>
    value.split(",").map((item) => item.trim()).filter(Boolean);

  const submit = () => {
    const trimmedName = name.trim();
    const trimmedRoot = rootPath.trim().replace(/^\/+|\/+$/g, "");
    if (!trimmedName || !defaultWorkspaceId) return;
    if (selectedBlueprintId) {
      createFromBlueprint.mutate({
        blueprint_id: selectedBlueprintId,
        workspace_id: defaultWorkspaceId,
        name: trimmedName,
        root_path: trimmedRoot || null,
      }, {
        onSuccess: () => {
          setName("");
          setRootPath("common/projects");
          setSelectedBlueprintId("");
          setCreating(false);
        },
      });
      return;
    }
    if (!trimmedRoot) return;
    createProject.mutate({
      workspace_id: defaultWorkspaceId,
      name: trimmedName,
      root_path: trimmedRoot,
    }, {
      onSuccess: () => {
        setName("");
        setRootPath("common/projects");
        setCreating(false);
      },
    });
  };

  const submitBlueprint = () => {
    const trimmedName = blueprintName.trim();
    if (!trimmedName || createBlueprint.isPending) return;
    createBlueprint.mutate({
      name: trimmedName,
      default_root_path_pattern: blueprintRootPattern.trim() || "common/projects/{slug}",
      folders: splitList(blueprintFolders),
      required_secrets: splitList(blueprintSecrets),
    }, {
      onSuccess: () => {
        setBlueprintName("");
        setBlueprintRootPattern("common/projects/{slug}");
        setBlueprintFolders(".spindrel,.spindrel/knowledge-base");
        setBlueprintSecrets("");
      },
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="list"
        title="Projects"
        subtitle="Shared working roots for files, terminals, search, and harness runs."
        right={
          <ActionButton
            label={creating ? "Close" : "New Project"}
            icon={!creating ? <Plus size={14} /> : undefined}
            variant={creating ? "secondary" : "primary"}
            onPress={() => setCreating((value) => !value)}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-6 px-5 py-5 md:px-6">
          {creating && (
            <div data-testid="project-workspace-create-form" className="rounded-md bg-surface-raised/35 px-3 py-3">
              <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,1fr)_auto] md:items-end">
                <FormRow label="Project name">
                  <TextInput
                    value={name}
                    onChangeText={setName}
                    placeholder="Project name"
                  />
                </FormRow>
                <FormRow label="Blueprint">
                  <SelectInput
                    value={selectedBlueprintId}
                    onChange={(value) => {
                      setSelectedBlueprintId(value);
                      setRootPath(value ? "" : "common/projects");
                    }}
                    options={blueprintOptions}
                  />
                </FormRow>
                <FormRow label="Root path">
                  <TextInput
                    value={rootPath}
                    onChangeText={setRootPath}
                    placeholder={selectedBlueprintId ? "Use blueprint pattern" : "common/projects"}
                  />
                </FormRow>
                <ActionButton
                  label="Create"
                  icon={<Plus size={14} />}
                  onPress={submit}
                  disabled={
                    !name.trim()
                    || (!selectedBlueprintId && !rootPath.trim())
                    || !defaultWorkspaceId
                    || createProject.isPending
                    || createFromBlueprint.isPending
                  }
                />
              </div>
            </div>
          )}

          <Section
            title="Project Roots"
            description="A Project is a named root inside the shared workspace. Channels can attach to the same root without sharing bot-private memory."
          >
            <div data-testid="project-workspace-list" className="flex flex-col gap-2">
              <SettingsGroupLabel
                label="Current projects"
                count={projects?.length ?? 0}
                icon={<FolderKanban size={13} className="text-text-dim" />}
                action={<QuietPill label={`${attachedCount} attached channels`} maxWidthClass="max-w-none" />}
              />
              {isLoading ? (
                <div className="py-10"><Spinner size={18} /></div>
              ) : (projects ?? []).length === 0 ? (
                <EmptyState
                  message="No Projects yet. Create one to share a working root across channels."
                  action={<ActionButton label="New Project" icon={<Plus size={14} />} onPress={() => setCreating(true)} />}
                />
              ) : (
                (projects ?? []).map((project) => (
                  <div key={project.id} data-testid="project-workspace-row">
                    <SettingsControlRow
                      onClick={() => navigate(`/admin/projects/${project.id}`)}
                      leading={<FolderKanban size={15} />}
                      title={project.name}
                      description={<span className="font-mono">/{project.root_path}</span>}
                      meta={
                        <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
                          <QuietPill label={project.slug} maxWidthClass="max-w-[180px]" />
                          <span>{project.attached_channel_count ?? 0} attached</span>
                        </span>
                      }
                    />
                  </div>
                ))
              )}
            </div>
          </Section>

          <Section
            title="Blueprints"
            description="Reusable recipes for new Project roots. v0 materializes folders, starter files, knowledge files, env defaults, repo declarations, and secret binding slots."
          >
            <div className="flex flex-col gap-3">
              <div className="grid gap-3 rounded-md bg-surface-raised/35 px-3 py-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
                <FormRow label="Blueprint name">
                  <TextInput
                    value={blueprintName}
                    onChangeText={setBlueprintName}
                    placeholder="Node service"
                  />
                </FormRow>
                <FormRow label="Root pattern">
                  <TextInput
                    value={blueprintRootPattern}
                    onChangeText={setBlueprintRootPattern}
                    placeholder="common/projects/{slug}"
                  />
                </FormRow>
                <FormRow label="Folders">
                  <TextInput
                    value={blueprintFolders}
                    onChangeText={setBlueprintFolders}
                    placeholder=".spindrel,docs"
                  />
                </FormRow>
                <FormRow label="Required secrets">
                  <TextInput
                    value={blueprintSecrets}
                    onChangeText={setBlueprintSecrets}
                    placeholder="GITHUB_TOKEN"
                  />
                </FormRow>
                <ActionButton
                  label="Add"
                  icon={<Plus size={14} />}
                  disabled={!blueprintName.trim() || createBlueprint.isPending}
                  onPress={submitBlueprint}
                />
              </div>
              <div data-testid="project-blueprint-list" className="flex flex-col gap-2">
                <SettingsGroupLabel
                  label="Available blueprints"
                  count={blueprints?.length ?? 0}
                  icon={<Layers size={13} className="text-text-dim" />}
                />
                {(blueprints ?? []).length === 0 ? (
                  <EmptyState message="No blueprints yet. Add one here or create one through the Projects API." />
                ) : (
                  (blueprints ?? []).map((blueprint) => (
                    <SettingsControlRow
                      key={blueprint.id}
                      leading={<Layers size={15} />}
                      title={blueprint.name}
                      description={<span className="font-mono">/{blueprint.default_root_path_pattern ?? "common/projects/{slug}"}</span>}
                      meta={
                        <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
                          <QuietPill label={blueprint.slug} maxWidthClass="max-w-[180px]" />
                          <span>{blueprint.required_secrets?.length ?? 0} secrets</span>
                        </span>
                      }
                    />
                  ))
                )}
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
