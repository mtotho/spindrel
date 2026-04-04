/**
 * Visual condition builder for workflow step conditions.
 * Structured mode: step + status dropdowns with AND/OR combinators.
 * Expression mode: raw JSON textarea for power users.
 */
import { useState, useCallback, useEffect } from "react";
import { View, Text, Pressable } from "react-native";
import { type ThemeTokens } from "@/src/theme/tokens";
import { Plus, X, GitBranch, Code } from "lucide-react";

interface ConditionBuilderProps {
  condition: Record<string, any> | null;
  onChange: (c: Record<string, any> | null) => void;
  priorStepIds: string[];
  disabled?: boolean;
  t: ThemeTokens;
}

// A single simple condition (step + status)
interface SimpleCondition {
  step: string;
  status: string;
}

/**
 * Parse a condition object into an array of simple conditions + combinator.
 * Returns null if it can't be parsed as simple conditions.
 */
function parseAsSimple(cond: Record<string, any> | null): {
  conditions: SimpleCondition[];
  combinator: "all" | "any";
} | null {
  if (!cond) return { conditions: [], combinator: "all" };

  // Single step+status
  if ("step" in cond && "status" in cond && Object.keys(cond).length === 2) {
    return { conditions: [{ step: cond.step, status: cond.status }], combinator: "all" };
  }

  // all: [...]
  if ("all" in cond && Array.isArray(cond.all)) {
    const items = cond.all as any[];
    if (items.every((i) => i.step && i.status && Object.keys(i).length === 2)) {
      return { conditions: items.map((i) => ({ step: i.step, status: i.status })), combinator: "all" };
    }
    return null;
  }

  // any: [...]
  if ("any" in cond && Array.isArray(cond.any)) {
    const items = cond.any as any[];
    if (items.every((i) => i.step && i.status && Object.keys(i).length === 2)) {
      return { conditions: items.map((i) => ({ step: i.step, status: i.status })), combinator: "any" };
    }
    return null;
  }

  return null;
}

/**
 * Convert simple conditions + combinator back to a condition object.
 */
function simplesToCondition(
  conditions: SimpleCondition[],
  combinator: "all" | "any",
): Record<string, any> | null {
  const valid = conditions.filter((c) => c.step);
  if (valid.length === 0) return null;
  if (valid.length === 1) return { step: valid[0].step, status: valid[0].status };
  return { [combinator]: valid.map((c) => ({ step: c.step, status: c.status })) };
}

export function WorkflowConditionBuilder({
  condition, onChange, priorStepIds, disabled, t,
}: ConditionBuilderProps) {
  const parsed = parseAsSimple(condition);
  const [showExpression, setShowExpression] = useState(parsed === null);
  const [jsonText, setJsonText] = useState(condition ? JSON.stringify(condition, null, 2) : "");
  const [conditions, setConditions] = useState<SimpleCondition[]>(parsed?.conditions || []);
  const [combinator, setCombinator] = useState<"all" | "any">(parsed?.combinator || "all");

  // Sync external changes
  useEffect(() => {
    const p = parseAsSimple(condition);
    if (p) {
      setConditions(p.conditions);
      setCombinator(p.combinator);
      setShowExpression(false);
    } else if (condition && Object.keys(condition).length > 0) {
      // Complex condition can't be represented in structured mode
      setShowExpression(true);
    }
    setJsonText(condition ? JSON.stringify(condition, null, 2) : "");
  }, [condition]);

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 6, padding: "6px 10px", color: t.inputText,
    fontSize: 12, outline: "none",
    opacity: disabled ? 0.6 : 1,
  };

  // Structured mode handlers
  const updateConditions = useCallback((next: SimpleCondition[], comb: "all" | "any") => {
    setConditions(next);
    const result = simplesToCondition(next, comb);
    onChange(result);
  }, [onChange]);

  const addCondition = useCallback(() => {
    const next = [...conditions, { step: priorStepIds[0] || "", status: "done" }];
    setConditions(next);
    onChange(simplesToCondition(next, combinator));
  }, [conditions, combinator, priorStepIds, onChange]);

  const removeCondition = useCallback((index: number) => {
    const next = conditions.filter((_, i) => i !== index);
    setConditions(next);
    onChange(simplesToCondition(next, combinator));
  }, [conditions, combinator, onChange]);

  const toggleCombinator = useCallback(() => {
    const next = combinator === "all" ? "any" : "all";
    setCombinator(next);
    onChange(simplesToCondition(conditions, next));
  }, [conditions, combinator, onChange]);

  const hasCondition = condition && Object.keys(condition).length > 0;

  // Expression mode
  if (showExpression) {
    let isValid = true;
    if (jsonText.trim()) {
      try { JSON.parse(jsonText); } catch { isValid = false; }
    }

    return (
      <div style={{
        padding: 10, borderRadius: 8,
        background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          marginBottom: 8,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Code size={12} color={t.textMuted} />
            <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>
              Condition Expression
            </span>
          </div>
          <button
            onClick={() => {
              const p = parseAsSimple(condition);
              if (p) {
                setConditions(p.conditions);
                setCombinator(p.combinator);
              }
              setShowExpression(false);
            }}
            style={{
              background: "none", border: "none", color: t.accent,
              fontSize: 11, cursor: "pointer", padding: 0,
            }}
          >
            Visual mode
          </button>
        </div>
        <textarea
          value={jsonText}
          onChange={(e) => {
            setJsonText(e.target.value);
            if (!e.target.value.trim()) {
              onChange(null);
              return;
            }
            try {
              const parsed = JSON.parse(e.target.value);
              onChange(parsed);
            } catch {
              // wait for valid JSON
            }
          }}
          placeholder='{"step": "step_1", "status": "done"}'
          rows={3}
          style={{
            ...inputStyle, fontFamily: "monospace", fontSize: 12,
            resize: "vertical" as const, width: "100%",
            borderColor: !isValid && jsonText.trim() ? t.danger : t.inputBorder,
          }}
          disabled={disabled}
        />
        {!isValid && jsonText.trim() && (
          <Text style={{ color: t.danger, fontSize: 10, marginTop: 4 }}>Invalid JSON</Text>
        )}
      </div>
    );
  }

  // Structured mode
  return (
    <div style={{
      padding: 10, borderRadius: 8,
      background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: conditions.length > 0 ? 8 : 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <GitBranch size={12} color={t.purple} />
          <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Condition
          </span>
          {!hasCondition && (
            <span style={{ fontSize: 11, color: t.textDim, fontStyle: "italic", textTransform: "none", letterSpacing: 0 }}>
              Always run
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {hasCondition && !disabled && (
            <button
              onClick={() => { onChange(null); setConditions([]); }}
              style={{
                background: "none", border: "none", color: t.textDim,
                fontSize: 11, cursor: "pointer", padding: 0,
              }}
            >
              Clear
            </button>
          )}
          <button
            onClick={() => setShowExpression(true)}
            style={{
              background: "none", border: "none", color: t.accent,
              fontSize: 11, cursor: "pointer", padding: 0,
            }}
          >
            Expression
          </button>
        </div>
      </div>

      {/* Condition rows */}
      {conditions.map((cond, i) => (
        <div key={i}>
          {/* AND/OR combinator between conditions */}
          {i > 0 && (
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              padding: "4px 0",
            }}>
              <button
                onClick={toggleCombinator}
                disabled={disabled}
                style={{
                  background: combinator === "all" ? t.accentSubtle : t.warningSubtle,
                  border: `1px solid ${combinator === "all" ? t.accentBorder : t.warningBorder}`,
                  color: combinator === "all" ? t.accent : t.warning,
                  fontSize: 10, fontWeight: 700, borderRadius: 4,
                  padding: "1px 8px", cursor: disabled ? "default" : "pointer",
                  textTransform: "uppercase", letterSpacing: 0.5,
                }}
              >
                {combinator === "all" ? "AND" : "OR"}
              </button>
            </div>
          )}

          <div style={{
            display: "flex", gap: 6, alignItems: "center",
          }}>
            <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>Step</span>
            <select
              value={cond.step}
              onChange={(e) => {
                const next = [...conditions];
                next[i] = { ...next[i], step: e.target.value };
                updateConditions(next, combinator);
              }}
              style={{ ...inputStyle, flex: 1, minWidth: 80, cursor: "pointer" }}
              disabled={disabled}
            >
              <option value="">Select step...</option>
              {priorStepIds.map((sid) => (
                <option key={sid} value={sid}>{sid}</option>
              ))}
            </select>
            <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>is</span>
            <select
              value={cond.status}
              onChange={(e) => {
                const next = [...conditions];
                next[i] = { ...next[i], status: e.target.value };
                updateConditions(next, combinator);
              }}
              style={{ ...inputStyle, width: 80, cursor: "pointer" }}
              disabled={disabled}
            >
              <option value="done">done</option>
              <option value="failed">failed</option>
              <option value="skipped">skipped</option>
            </select>
            {!disabled && (
              <button
                onClick={() => removeCondition(i)}
                style={{
                  background: "none", border: "none", padding: 2,
                  cursor: "pointer", display: "flex", opacity: 0.5,
                }}
              >
                <X size={12} color={t.textDim} />
              </button>
            )}
          </div>
        </div>
      ))}

      {/* Add condition button */}
      {!disabled && priorStepIds.length > 0 && (
        <Pressable
          onPress={addCondition}
          style={{
            flexDirection: "row", alignItems: "center", gap: 4,
            paddingVertical: 6, paddingTop: conditions.length > 0 ? 8 : 4,
          }}
        >
          <Plus size={11} color={t.accent} />
          <Text style={{ color: t.accent, fontSize: 11 }}>
            {conditions.length === 0 ? "Add condition" : "Add another"}
          </Text>
        </Pressable>
      )}

      {priorStepIds.length === 0 && conditions.length === 0 && (
        <Text style={{ color: t.textDim, fontSize: 11, fontStyle: "italic", marginTop: 4 }}>
          Conditions require prior steps to reference.
        </Text>
      )}
    </div>
  );
}
