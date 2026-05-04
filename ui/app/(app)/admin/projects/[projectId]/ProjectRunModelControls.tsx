import { useMemo } from "react";

import type { ProjectChannel, ProjectRunModelSelectionInput } from "@/src/api/hooks/useProjects";
import { useRuntimeCapabilities } from "@/src/api/hooks/useRuntimes";
import { FormRow, SelectInput } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";

interface ProjectRunModelControlsProps {
  channel?: ProjectChannel | null;
  value: ProjectRunModelSelectionInput;
  onChange: (value: ProjectRunModelSelectionInput) => void;
}

export function ProjectRunModelControls({
  channel,
  value,
  onChange,
}: ProjectRunModelControlsProps) {
  const runtime = channel?.harness_runtime ?? null;
  const { data: caps } = useRuntimeCapabilities(runtime);
  const modelOptions = useMemo(() => {
    const ids = caps?.model_options?.length
      ? caps.model_options.map((option) => option.id)
      : caps?.available_models ?? [];
    const values = value.model_override && !ids.includes(value.model_override)
      ? [value.model_override, ...ids]
      : ids;
    return [
      { label: "Runtime default", value: "" },
      ...values.map((id) => ({ label: id, value: id })),
    ];
  }, [caps?.available_models, caps?.model_options, value.model_override]);
  const effortOptions = useMemo(() => {
    const selectedModel = value.model_override || caps?.default_model || "";
    const efforts = (
      caps?.model_options?.find((option) => option.id === selectedModel)?.effort_values
      ?? caps?.effort_values
      ?? []
    );
    const values = value.harness_effort && !efforts.includes(value.harness_effort)
      ? [value.harness_effort, ...efforts]
      : efforts;
    return [
      { label: "Preset default", value: "" },
      ...values.map((effort) => ({ label: effort, value: effort })),
    ];
  }, [caps?.default_model, caps?.effort_values, caps?.model_options, value.harness_effort, value.model_override]);

  if (!channel) return null;

  if (runtime) {
    return (
      <div className="grid gap-2">
        <FormRow label="Harness model">
          <SelectInput
            value={value.model_override || ""}
            onChange={(model) => onChange({
              model_override: model || null,
              model_provider_id_override: null,
              harness_effort: value.harness_effort ?? null,
            })}
            options={modelOptions}
          />
        </FormRow>
        {effortOptions.length > 1 && (
          <FormRow label="Harness effort">
            <SelectInput
              value={value.harness_effort || ""}
              onChange={(effort) => onChange({
                model_override: value.model_override ?? null,
                model_provider_id_override: null,
                harness_effort: effort || null,
              })}
              options={effortOptions}
            />
          </FormRow>
        )}
      </div>
    );
  }

  return (
    <FormRow label="Model override">
      <LlmModelDropdown
        value={value.model_override || ""}
        selectedProviderId={value.model_provider_id_override ?? undefined}
        placeholder={channel.model_override || channel.bot_model || "Channel default"}
        onChange={(model, providerId) => onChange({
          model_override: model || null,
          model_provider_id_override: model ? providerId ?? null : null,
          harness_effort: null,
        })}
      />
    </FormRow>
  );
}
