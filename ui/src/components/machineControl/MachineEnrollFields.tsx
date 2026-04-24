import { FormRow, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { SelectDropdown } from "@/src/components/shared/SelectDropdown";
import type { MachineControlEnrollField } from "@/src/api/hooks/useMachineTargets";

export type MachineEnrollDraft = Record<string, string | boolean>;

function normalizeDefault(field: MachineControlEnrollField): string | boolean {
  if (field.type === "boolean") return Boolean(field.default);
  if (field.default === null || field.default === undefined) return "";
  return String(field.default);
}

export function buildMachineEnrollDraft(fields?: MachineControlEnrollField[] | null): MachineEnrollDraft {
  const draft: MachineEnrollDraft = {};
  for (const field of fields ?? []) {
    if (!field?.key) continue;
    draft[field.key] = normalizeDefault(field);
  }
  return draft;
}

export function normalizeMachineEnrollConfig(
  fields: MachineControlEnrollField[] | null | undefined,
  draft: MachineEnrollDraft,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  for (const field of fields ?? []) {
    if (!field?.key) continue;
    const raw = draft[field.key];
    if (field.type === "boolean") {
      payload[field.key] = Boolean(raw);
      continue;
    }
    const text = String(raw ?? "").trim();
    if (!text) continue;
    if (field.type === "number") {
      const parsed = Number(text);
      if (!Number.isNaN(parsed)) payload[field.key] = parsed;
      continue;
    }
    payload[field.key] = text;
  }
  return payload;
}

export function MachineEnrollFields({
  fields,
  draft,
  onChange,
  disabled,
}: {
  fields?: MachineControlEnrollField[] | null;
  draft: MachineEnrollDraft;
  onChange: (key: string, value: string | boolean) => void;
  disabled?: boolean;
}) {
  const usableFields = fields ?? [];
  if (!usableFields.length) return null;

  return (
    <div className="grid w-full gap-3 md:grid-cols-2">
      {usableFields.map((field) => {
        const key = field.key;
        const value = draft[key];
        const label = `${field.label || key}${field.required ? " *" : ""}`;
        const description = field.description || undefined;

        if (field.type === "boolean") {
          return (
            <div key={key} className="md:col-span-2">
              <Toggle
                value={Boolean(value)}
                onChange={(next) => onChange(key, next)}
                label={label}
                description={description}
              />
            </div>
          );
        }

        if (field.type === "select" && field.options?.length) {
          return (
            <FormRow key={key} label={label} description={description}>
              <SelectDropdown
                value={String(value ?? "")}
                onChange={(next) => onChange(key, next)}
                options={[
                  { value: "", label: "Select..." },
                  ...field.options.map((option) => ({
                    value: option.value,
                    label: option.label,
                    searchText: `${option.label} ${option.value}`,
                  })),
                ]}
                disabled={disabled}
                searchable={field.options.length > 8}
                popoverWidth="content"
              />
            </FormRow>
          );
        }

        if (field.multiline) {
          return (
            <FormRow key={key} label={label} description={description}>
              <textarea
                value={String(value ?? "")}
                disabled={disabled}
                onChange={(event) => onChange(key, event.target.value)}
                placeholder={field.description || ""}
                rows={5}
                className="min-h-[120px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text placeholder:text-text-dim focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/40 disabled:cursor-default disabled:opacity-50"
              />
            </FormRow>
          );
        }

        return (
          <FormRow key={key} label={label} description={description}>
            <TextInput
              type={field.type === "number" ? "number" : field.secret ? "password" : "text"}
              value={String(value ?? "")}
              onChangeText={(next) => onChange(key, next)}
              placeholder={field.description || ""}
              disabled={disabled}
            />
          </FormRow>
        );
      })}
    </div>
  );
}
