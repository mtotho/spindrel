import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { X, BookTemplate } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { channelColor } from "./botColors";
import {
  StepListEditor,
  makeStepKey,
  type StepDraft,
} from "./StepListEditor";
import { useMCPlanTemplates, type MCPlanTemplate } from "@/src/api/hooks/useMissionControl";

interface PlanCreateFormProps {
  channels: Array<{ id: string; name: string }>;
  onSubmit: (data: {
    channelId: string;
    title: string;
    notes: string;
    steps: Array<{ content: string; requires_approval: boolean }>;
  }) => void;
  onCancel: () => void;
  isPending?: boolean;
}

export function PlanCreateForm({
  channels,
  onSubmit,
  onCancel,
  isPending,
}: PlanCreateFormProps) {
  const t = useThemeTokens();
  const { data: templatesData } = useMCPlanTemplates();
  const templates = templatesData?.templates || [];
  const [channelId, setChannelId] = useState(channels[0]?.id || "");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [steps, setSteps] = useState<StepDraft[]>([
    { key: makeStepKey(), content: "", requires_approval: false },
  ]);

  const applyTemplate = (tmpl: MCPlanTemplate) => {
    setTitle(tmpl.name);
    setNotes(tmpl.description);
    try {
      const parsed = JSON.parse(tmpl.steps_json) as Array<{ content: string; requires_approval?: boolean }>;
      setSteps(
        parsed.map((s) => ({
          key: makeStepKey(),
          content: s.content,
          requires_approval: s.requires_approval ?? false,
        })),
      );
    } catch {
      // ignore bad template data
    }
  };

  const canSubmit =
    channelId &&
    title.trim() &&
    steps.length > 0 &&
    steps.every((s) => s.content.trim());

  const handleSubmit = () => {
    if (!canSubmit || isPending) return;
    onSubmit({
      channelId,
      title: title.trim(),
      notes: notes.trim(),
      steps: steps.map((s) => ({
        content: s.content.trim(),
        requires_approval: s.requires_approval,
      })),
    });
  };

  return (
    <View
      className="rounded-xl border border-surface-border"
      style={{ padding: 16, gap: 14, backgroundColor: t.surfaceOverlay }}
    >
      <View className="flex-row items-center justify-between">
        <Text style={{ fontSize: 14, fontWeight: "600", color: t.text }}>
          Create Plan
        </Text>
        <Pressable onPress={onCancel} style={{ padding: 4 }}>
          <X size={16} color={t.textDim} />
        </Pressable>
      </View>

      {/* Channel selector */}
      {channels.length > 1 && (
        <View style={{ gap: 4 }}>
          <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "600" }}>
            Channel
          </Text>
          <View className="flex-row flex-wrap gap-2">
            {channels.map((ch) => {
              const active = channelId === ch.id;
              const cc = channelColor(ch.id);
              return (
                <Pressable
                  key={ch.id}
                  onPress={() => setChannelId(ch.id)}
                  className={`rounded-full px-3 py-1 border flex-row items-center gap-1.5 ${
                    active
                      ? "border-accent bg-accent/10"
                      : "border-surface-border"
                  }`}
                >
                  <View
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 3,
                      backgroundColor: cc,
                    }}
                  />
                  <Text
                    className={`text-xs ${
                      active ? "text-accent font-medium" : "text-text-muted"
                    }`}
                  >
                    {ch.name}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      )}

      {/* From template */}
      {templates.length > 0 && (
        <View style={{ gap: 4 }}>
          <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "600" }}>
            From Template
          </Text>
          <View className="flex-row flex-wrap gap-2">
            {templates.map((tmpl) => (
              <Pressable
                key={tmpl.id}
                onPress={() => applyTemplate(tmpl)}
                className="flex-row items-center gap-1.5 rounded-full px-3 py-1 border border-surface-border"
              >
                <BookTemplate size={10} color={t.textDim} />
                <Text style={{ fontSize: 11, color: t.text }}>{tmpl.name}</Text>
              </Pressable>
            ))}
          </View>
        </View>
      )}

      {/* Title */}
      <View style={{ gap: 4 }}>
        <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "600" }}>
          Title
        </Text>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Plan title..."
          style={{
            fontSize: 13,
            color: t.text,
            backgroundColor: t.surface,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            padding: "8px 10px",
            outline: "none",
            fontFamily: "inherit",
          }}
        />
      </View>

      {/* Notes */}
      <View style={{ gap: 4 }}>
        <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "600" }}>
          Notes (optional)
        </Text>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Context, rationale, estimates..."
          rows={2}
          style={{
            fontSize: 13,
            color: t.text,
            backgroundColor: t.surface,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            padding: "8px 10px",
            outline: "none",
            fontFamily: "inherit",
            resize: "vertical",
          }}
        />
      </View>

      {/* Steps */}
      <View style={{ gap: 4 }}>
        <Text style={{ fontSize: 11, color: t.textDim, fontWeight: "600" }}>
          Steps
        </Text>
        <StepListEditor steps={steps} onChange={setSteps} />
      </View>

      {/* Actions */}
      <View className="flex-row items-center gap-2 pt-1">
        <Pressable
          onPress={handleSubmit}
          disabled={!canSubmit || isPending}
          className="flex-row items-center gap-1.5 rounded-lg px-4 py-2"
          style={{
            backgroundColor:
              canSubmit && !isPending
                ? "rgba(34,197,94,0.15)"
                : t.surfaceOverlay,
            borderWidth: 1,
            borderColor:
              canSubmit && !isPending
                ? "rgba(34,197,94,0.4)"
                : t.surfaceBorder,
            opacity: canSubmit && !isPending ? 1 : 0.5,
          }}
        >
          {isPending && <ActivityIndicator size="small" color="#22c55e" />}
          <Text
            style={{
              fontSize: 13,
              fontWeight: "600",
              color: canSubmit ? "#22c55e" : t.textDim,
            }}
          >
            Create Plan
          </Text>
        </Pressable>
        <Pressable
          onPress={onCancel}
          className="rounded-lg px-3 py-2"
          style={{
            borderWidth: 1,
            borderColor: t.surfaceBorder,
          }}
        >
          <Text style={{ fontSize: 13, color: t.textDim }}>Cancel</Text>
        </Pressable>
      </View>
    </View>
  );
}
