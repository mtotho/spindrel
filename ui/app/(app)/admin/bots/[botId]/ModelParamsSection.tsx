import { useThemeTokens } from "@/src/theme/tokens";
import { FormRow, Slider } from "@/src/components/shared/FormControls";
import type { ModelParamDefinition } from "@/src/types/api";

const REASONING_PARAMS = new Set(["effort", "reasoning_effort", "thinking_budget"]);

export function ModelParamsSection({
  definitions,
  support,
  reasoningCapableModels,
  model,
  params,
  onChange,
}: {
  definitions: ModelParamDefinition[];
  support: Record<string, string[]>;
  reasoningCapableModels?: string[];
  model: string;
  params: Record<string, any>;
  onChange: (p: Record<string, any>) => void;
}) {
  // Derive provider family from model string
  const family = model.includes("/") ? model.split("/")[0].toLowerCase() : "openai";
  const supported = new Set(support[family] || support["_default"] || ["temperature", "max_tokens"]);
  const reasoningCapable = new Set(reasoningCapableModels ?? []);
  const modelSupportsReasoning = !!model && reasoningCapable.has(model);

  const t = useThemeTokens();

  const setParam = (name: string, value: any) => {
    const next = { ...params };
    if (value === undefined) {
      delete next[name];
    } else {
      next[name] = value;
    }
    onChange(next);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginTop: 4 }}>Model Parameters</div>
      {definitions.map((def) => {
        const isFamilySupported = supported.has(def.name);
        const isReasoningParam = REASONING_PARAMS.has(def.name);
        const gatedByReasoning = isReasoningParam && !modelSupportsReasoning;
        const isSupported = isFamilySupported && !gatedByReasoning;
        const hasValue = params[def.name] !== undefined;
        const currentValue = hasValue ? params[def.name] : (def.default ?? 0);
        const descBase = gatedByReasoning
          ? `Model ${model || "(unset)"} is not marked as reasoning-capable — toggle on the admin providers page`
          : !isFamilySupported
            ? `Not supported by ${family} models`
            : def.description;
        const desc = `${descBase} · ${def.name}`;

        return (
          <FormRow key={def.name} label={def.label} description={desc}>
            {def.type === "slider" ? (
              <Slider
                value={currentValue}
                onChange={(v) => setParam(def.name, v)}
                min={def.min ?? 0}
                max={def.max ?? 1}
                step={def.step ?? 0.01}
                disabled={!isSupported}
                defaultValue={typeof def.default === "number" ? def.default : null}
              />
            ) : def.type === "select" ? (
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                <select
                  value={hasValue ? params[def.name] : ""}
                  onChange={(e) => setParam(def.name, e.target.value || undefined)}
                  disabled={!isSupported}
                  style={{
                    background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 8,
                    padding: "7px 12px", color: t.text, fontSize: 13, maxWidth: 200, width: "100%",
                    outline: "none", opacity: isSupported ? 1 : 0.4, cursor: isSupported ? "pointer" : "not-allowed",
                  }}
                >
                  <option value="">Default</option>
                  {((def as any).options || []).map((opt: string) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
                <input
                  type="number"
                  value={hasValue ? params[def.name] : ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v === "") {
                      setParam(def.name, undefined);
                    } else {
                      setParam(def.name, parseInt(v, 10));
                    }
                  }}
                  placeholder={def.default != null ? `Default: ${def.default}` : "Model default"}
                  min={def.min}
                  max={def.max}
                  disabled={!isSupported}
                  style={{
                    background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 8,
                    padding: "7px 12px", color: t.text, fontSize: 13, maxWidth: 200, width: "100%",
                    outline: "none", opacity: isSupported ? 1 : 0.4,
                  }}
                />
                {hasValue && (
                  <button
                    onClick={() => setParam(def.name, undefined)}
                    style={{
                      fontSize: 10, color: t.textDim, background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
                      borderRadius: 4, padding: "2px 6px", cursor: "pointer",
                    }}
                  >
                    clear
                  </button>
                )}
              </div>
            )}
          </FormRow>
        );
      })}
    </div>
  );
}
