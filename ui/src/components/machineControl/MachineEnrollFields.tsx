import type { ThemeTokens } from "@/src/theme/tokens";
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
  t,
}: {
  fields?: MachineControlEnrollField[] | null;
  draft: MachineEnrollDraft;
  onChange: (key: string, value: string | boolean) => void;
  disabled?: boolean;
  t: ThemeTokens;
}) {
  const usableFields = fields ?? [];
  if (!usableFields.length) return null;

  return (
    <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", width: "100%" }}>
      {usableFields.map((field) => {
        const key = field.key;
        const value = draft[key];
        const label = field.label || key;
        const description = field.description || null;

        if (field.type === "boolean") {
          return (
            <label
              key={key}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                minHeight: 36,
                color: t.text,
                fontSize: 12,
              }}
            >
              <input
                type="checkbox"
                checked={Boolean(value)}
                disabled={disabled}
                onChange={(event) => onChange(key, event.target.checked)}
              />
              <span>
                {label}
                {description ? <span style={{ color: t.textDim }}> · {description}</span> : null}
              </span>
            </label>
          );
        }

        return (
          <label key={key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: t.textDim }}>
              {label}
              {field.required ? " *" : ""}
            </span>
            {field.type === "select" && field.options?.length ? (
              <select
                value={String(value ?? "")}
                disabled={disabled}
                onChange={(event) => onChange(key, event.target.value)}
                style={{
                  minHeight: 36,
                  borderRadius: 6,
                  border: `1px solid ${t.inputBorder}`,
                  background: t.inputBg,
                  color: t.text,
                  padding: "8px 10px",
                  fontSize: 12,
                }}
              >
                <option value="">Select…</option>
                {field.options.map((option) => (
                  <option key={`${key}:${option.value}`} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={field.type === "number" ? "number" : "text"}
                value={String(value ?? "")}
                disabled={disabled}
                onChange={(event) => onChange(key, event.target.value)}
                placeholder={field.description || ""}
                style={{
                  minHeight: 36,
                  borderRadius: 6,
                  border: `1px solid ${t.inputBorder}`,
                  background: t.inputBg,
                  color: t.text,
                  padding: "8px 10px",
                  fontSize: 12,
                }}
              />
            )}
            {description ? (
              <span style={{ fontSize: 11, color: t.textDim }}>{description}</span>
            ) : null}
          </label>
        );
      })}
    </div>
  );
}
