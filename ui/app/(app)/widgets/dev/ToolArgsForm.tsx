import type { ChangeEvent } from "react";

interface Props {
  schema: Record<string, any> | null | undefined;
  values: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
}

type JsonValue = unknown;

function coerce(type: string | undefined, raw: string): JsonValue {
  if (raw === "") return undefined;
  if (type === "integer") {
    const n = parseInt(raw, 10);
    return Number.isFinite(n) ? n : raw;
  }
  if (type === "number") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  if (type === "boolean") return raw === "true";
  if (type === "array" || type === "object") {
    try {
      return JSON.parse(raw);
    } catch {
      return raw; // user still typing
    }
  }
  return raw;
}

/**
 * Minimal JSONSchema-driven form. Renders top-level properties from an
 * OpenAI-style tool `parameters` object. Non-primitive types (array/object)
 * fall back to a JSON textarea so complex inputs are still reachable.
 */
export function ToolArgsForm({ schema, values, onChange }: Props) {
  const props = (schema?.properties ?? {}) as Record<string, any>;
  const required: string[] = schema?.required ?? [];
  const keys = Object.keys(props);

  if (keys.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-surface-border px-3 py-4 text-center text-[12px] text-text-dim">
        No arguments for this tool.
      </div>
    );
  }

  const update = (key: string, value: JsonValue) => {
    const next = { ...values };
    if (value === undefined) {
      delete next[key];
    } else {
      next[key] = value;
    }
    onChange(next);
  };

  return (
    <div className="flex flex-col gap-3">
      {keys.map((key) => {
        const spec = props[key] ?? {};
        const type: string = spec.type || (spec.enum ? "string" : "string");
        const current = values[key];
        const isRequired = required.includes(key);
        const label = (
          <div className="flex items-baseline gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-text-dim">
              {key}
            </span>
            {isRequired && <span className="text-[10px] text-danger">required</span>}
            <span className="text-[10px] text-text-dim font-mono">{type}</span>
          </div>
        );

        if (spec.enum && Array.isArray(spec.enum)) {
          return (
            <label key={key} className="flex flex-col gap-1">
              {label}
              <select
                value={current == null ? "" : String(current)}
                onChange={(e: ChangeEvent<HTMLSelectElement>) =>
                  update(key, e.target.value === "" ? undefined : e.target.value)
                }
                className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/40"
              >
                <option value="">—</option>
                {spec.enum.map((v: string) => (
                  <option key={String(v)} value={String(v)}>
                    {String(v)}
                  </option>
                ))}
              </select>
              {spec.description && (
                <span className="text-[11px] text-text-dim">{spec.description}</span>
              )}
            </label>
          );
        }

        if (type === "boolean") {
          return (
            <label key={key} className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={current === true}
                onChange={(e) => update(key, e.target.checked)}
                className="mt-1"
              />
              <div className="flex flex-col gap-0.5">
                {label}
                {spec.description && (
                  <span className="text-[11px] text-text-dim">{spec.description}</span>
                )}
              </div>
            </label>
          );
        }

        if (type === "array" || type === "object") {
          const display =
            current === undefined
              ? ""
              : typeof current === "string"
              ? current
              : JSON.stringify(current, null, 2);
          return (
            <label key={key} className="flex flex-col gap-1">
              {label}
              <textarea
                value={display}
                onChange={(e) => update(key, coerce(type, e.target.value))}
                rows={3}
                placeholder={type === "array" ? "[]" : "{}"}
                className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[12px] font-mono text-text outline-none focus:border-accent/40"
              />
              {spec.description && (
                <span className="text-[11px] text-text-dim">{spec.description}</span>
              )}
            </label>
          );
        }

        return (
          <label key={key} className="flex flex-col gap-1">
            {label}
            <input
              type={type === "integer" || type === "number" ? "number" : "text"}
              value={current == null ? "" : String(current)}
              onChange={(e) => update(key, coerce(type, e.target.value))}
              placeholder={spec.default != null ? String(spec.default) : ""}
              className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/40"
            />
            {spec.description && (
              <span className="text-[11px] text-text-dim">{spec.description}</span>
            )}
          </label>
        );
      })}
    </div>
  );
}
