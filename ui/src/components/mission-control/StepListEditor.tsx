import { View, Text, Pressable } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import { ShieldAlert, ArrowUp, ArrowDown, X, Plus } from "lucide-react";

export interface StepDraft {
  key: string;
  content: string;
  requires_approval: boolean;
}

let nextKey = 1;
export function makeStepKey(): string {
  return `step-${nextKey++}-${Math.random().toString(36).slice(2, 6)}`;
}

interface StepListEditorProps {
  steps: StepDraft[];
  onChange: (steps: StepDraft[]) => void;
}

export function StepListEditor({ steps, onChange }: StepListEditorProps) {
  const t = useThemeTokens();

  const updateStep = (key: string, field: Partial<StepDraft>) => {
    onChange(steps.map((s) => (s.key === key ? { ...s, ...field } : s)));
  };

  const removeStep = (key: string) => {
    if (steps.length <= 1) return;
    onChange(steps.filter((s) => s.key !== key));
  };

  const moveStep = (index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= steps.length) return;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  const addStep = () => {
    onChange([
      ...steps,
      { key: makeStepKey(), content: "", requires_approval: false },
    ]);
  };

  return (
    <View style={{ gap: 6 }}>
      {steps.map((step, i) => (
        <View
          key={step.key}
          className="flex-row items-center gap-2"
          style={{ minHeight: 36 }}
        >
          <Text
            style={{
              fontSize: 12,
              color: t.textDim,
              width: 20,
              textAlign: "right",
              fontFamily: "monospace",
            }}
          >
            {i + 1}
          </Text>
          <input
            type="text"
            value={step.content}
            onChange={(e) => updateStep(step.key, { content: e.target.value })}
            placeholder="Step description..."
            style={{
              flex: 1,
              fontSize: 13,
              color: t.text,
              backgroundColor: t.surfaceOverlay,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6,
              padding: "6px 10px",
              outline: "none",
              fontFamily: "inherit",
            }}
          />
          <Pressable
            onPress={() =>
              updateStep(step.key, {
                requires_approval: !step.requires_approval,
              })
            }
            style={{ padding: 4, opacity: step.requires_approval ? 1 : 0.3 }}
            accessibilityLabel="Toggle approval gate"
          >
            <ShieldAlert
              size={14}
              color={step.requires_approval ? "#a855f7" : t.textDim}
            />
          </Pressable>
          <Pressable
            onPress={() => moveStep(i, -1)}
            disabled={i === 0}
            style={{ padding: 4, opacity: i === 0 ? 0.2 : 0.6 }}
          >
            <ArrowUp size={13} color={t.textDim} />
          </Pressable>
          <Pressable
            onPress={() => moveStep(i, 1)}
            disabled={i === steps.length - 1}
            style={{
              padding: 4,
              opacity: i === steps.length - 1 ? 0.2 : 0.6,
            }}
          >
            <ArrowDown size={13} color={t.textDim} />
          </Pressable>
          <Pressable
            onPress={() => removeStep(step.key)}
            disabled={steps.length <= 1}
            style={{ padding: 4, opacity: steps.length <= 1 ? 0.2 : 0.6 }}
          >
            <X size={13} color="#ef4444" />
          </Pressable>
        </View>
      ))}

      <Pressable
        onPress={addStep}
        className="flex-row items-center gap-1.5 self-start rounded-lg px-3 py-1.5"
        style={{
          backgroundColor: t.surfaceOverlay,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          marginTop: 2,
        }}
      >
        <Plus size={12} color={t.textDim} />
        <Text style={{ fontSize: 12, color: t.textDim }}>Add Step</Text>
      </Pressable>
    </View>
  );
}
