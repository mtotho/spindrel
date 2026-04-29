import { ArrowLeft, Layers, Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useCreateProjectBlueprint, useProjectBlueprints } from "@/src/api/hooks/useProjects";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { FormRow, Section, TextInput } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";

export default function ProjectBlueprintsIndex() {
  const navigate = useNavigate();
  const { data: blueprints, isLoading } = useProjectBlueprints();
  const createBlueprint = useCreateProjectBlueprint();
  const [name, setName] = useState("");
  const [rootPattern, setRootPattern] = useState("common/projects/{slug}");

  const create = () => {
    const trimmedName = name.trim();
    if (!trimmedName || createBlueprint.isPending) return;
    createBlueprint.mutate({
      name: trimmedName,
      default_root_path_pattern: rootPattern.trim() || "common/projects/{slug}",
      folders: [".spindrel", ".spindrel/knowledge-base"],
    }, {
      onSuccess: (blueprint) => {
        setName("");
        setRootPattern("common/projects/{slug}");
        navigate(`/admin/projects/blueprints/${blueprint.id}`);
      },
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="list"
        title="Project Blueprints"
        subtitle="Reusable recipes for creating Project work surfaces."
        backTo="/admin/projects"
        right={
          <ActionButton
            label="Projects"
            icon={<ArrowLeft size={14} />}
            variant="secondary"
            onPress={() => navigate("/admin/projects")}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
          <Section
            title="New Blueprint"
            description="Start with a name and root pattern, then fill out files, repos, env defaults, and secret slots in the editor."
          >
            <div data-testid="project-blueprint-create" className="grid gap-3 rounded-md bg-surface-raised/35 px-3 py-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
              <FormRow label="Blueprint name">
                <TextInput
                  value={name}
                  onChangeText={setName}
                  placeholder="Node service"
                />
              </FormRow>
              <FormRow label="Root pattern">
                <TextInput
                  value={rootPattern}
                  onChangeText={setRootPattern}
                  placeholder="common/projects/{slug}"
                />
              </FormRow>
              <ActionButton
                label="Create"
                icon={<Plus size={14} />}
                disabled={!name.trim() || createBlueprint.isPending}
                onPress={create}
              />
            </div>
          </Section>

          <Section
            title="Blueprint Library"
            description="Open a recipe to edit its starter surface and declarations."
          >
            <div data-testid="project-blueprints-page" className="flex flex-col gap-2">
              <SettingsGroupLabel
                label="Blueprints"
                count={blueprints?.length ?? 0}
                icon={<Layers size={13} className="text-text-dim" />}
              />
              {isLoading ? (
                <div className="py-10"><Spinner size={18} /></div>
              ) : (blueprints ?? []).length === 0 ? (
                <EmptyState message="No Project Blueprints yet." />
              ) : (
                (blueprints ?? []).map((blueprint) => (
                  <div key={blueprint.id} data-testid="project-blueprint-row">
                    <SettingsControlRow
                      onClick={() => navigate(`/admin/projects/blueprints/${blueprint.id}`)}
                      leading={<Layers size={15} />}
                      title={blueprint.name}
                      description={<span className="font-mono">/{blueprint.default_root_path_pattern ?? "common/projects/{slug}"}</span>}
                      meta={
                        <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
                          <QuietPill label={blueprint.slug} maxWidthClass="max-w-[180px]" />
                          <span>{Object.keys(blueprint.files ?? {}).length} files</span>
                          <span>{blueprint.repos?.length ?? 0} repos</span>
                          <span>{blueprint.required_secrets?.length ?? 0} secrets</span>
                        </span>
                      }
                    />
                  </div>
                ))
              )}
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
