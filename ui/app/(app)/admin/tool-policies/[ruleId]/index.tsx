import { useState, useCallback } from "react";
import { View, ScrollView, ActivityIndicator } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { Trash2, Play } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { DetailHeader } from "@/src/components/layout/DetailHeader";
import {
  useToolPolicies,
  useCreateToolPolicy,
  useUpdateToolPolicy,
  useDeleteToolPolicy,
  useTestToolPolicy,
} from "@/src/api/hooks/useToolPolicies";
import {
  Section,
  FormRow,
  TextInput,
  SelectInput,
  Toggle,
} from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

const ACTION_OPTIONS = [
  { label: "Allow", value: "allow" },
  { label: "Deny", value: "deny" },
  { label: "Require Approval", value: "require_approval" },
];

export default function ToolPolicyDetailScreen() {
  const t = useThemeTokens();
  const params = useLocalSearchParams<{ ruleId: string; bot_id?: string }>();
  const ruleId = params.ruleId;
  const isNew = ruleId === "new";
  const goBack = useGoBack("/admin/tool-policies");

  const { data: allRules, isLoading } = useToolPolicies();
  const rule = allRules?.find((r) => r.id === ruleId);

  const createMut = useCreateToolPolicy();
  const updateMut = useUpdateToolPolicy(ruleId);
  const deleteMut = useDeleteToolPolicy();
  const testMut = useTestToolPolicy();

  const [toolName, setToolName] = useState("");
  const [action, setAction] = useState("deny");
  const [botId, setBotId] = useState(isNew && params.bot_id ? params.bot_id : "");
  const [priority, setPriority] = useState("100");
  const [reason, setReason] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [approvalTimeout, setApprovalTimeout] = useState("300");
  const [conditionsJson, setConditionsJson] = useState("{}");
  const [initialized, setInitialized] = useState(isNew);

  // Test panel state
  const [testBotId, setTestBotId] = useState("");
  const [testToolName, setTestToolName] = useState("");
  const [testArgsJson, setTestArgsJson] = useState("{}");
  const [testResult, setTestResult] = useState<string | null>(null);

  // Initialize from loaded data
  if (rule && !initialized) {
    setToolName(rule.tool_name);
    setAction(rule.action);
    setBotId(rule.bot_id || "");
    setPriority(String(rule.priority));
    setReason(rule.reason || "");
    setEnabled(rule.enabled);
    setApprovalTimeout(String(rule.approval_timeout));
    setConditionsJson(JSON.stringify(rule.conditions, null, 2));
    setInitialized(true);
  }

  const isSaving = createMut.isPending || updateMut.isPending;

  const handleSave = useCallback(async () => {
    let conditions = {};
    try {
      conditions = JSON.parse(conditionsJson);
    } catch {
      alert("Invalid JSON in conditions");
      return;
    }

    const data = {
      tool_name: toolName.trim(),
      action,
      bot_id: botId.trim() || null,
      priority: parseInt(priority) || 100,
      reason: reason.trim() || null,
      enabled,
      approval_timeout: parseInt(approvalTimeout) || 300,
      conditions,
    };

    if (isNew) {
      await createMut.mutateAsync(data);
      goBack();
    } else {
      await updateMut.mutateAsync(data);
    }
  }, [
    isNew,
    toolName,
    action,
    botId,
    priority,
    reason,
    enabled,
    approvalTimeout,
    conditionsJson,
    createMut,
    updateMut,
    goBack,
  ]);

  const handleDelete = useCallback(async () => {
    if (!confirm("Delete this policy rule?")) return;
    await deleteMut.mutateAsync(ruleId!);
    goBack();
  }, [ruleId, deleteMut, goBack]);

  const handleTest = useCallback(async () => {
    let args = {};
    try {
      args = JSON.parse(testArgsJson);
    } catch {
      setTestResult("Invalid JSON in test arguments");
      return;
    }
    const result = await testMut.mutateAsync({
      bot_id: testBotId.trim() || "default",
      tool_name: testToolName.trim() || toolName.trim(),
      arguments: args,
    });
    setTestResult(
      `Action: ${result.action}${result.reason ? ` | Reason: ${result.reason}` : ""}${
        result.rule_id ? ` | Rule: ${result.rule_id.substring(0, 8)}...` : " | No rule matched"
      }`
    );
  }, [testBotId, testToolName, testArgsJson, toolName, testMut]);

  if (!isNew && isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <DetailHeader
        parentLabel="Tool Policies"
        parentHref="/admin/tool-policies"
        title={isNew ? "New Policy Rule" : "Edit Policy Rule"}
        right={
          <>
            {!isNew && (
              <button
                onClick={handleDelete}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "6px 12px",
                  borderRadius: 6,
                  background: t.dangerSubtle,
                  border: `1px solid ${t.dangerBorder}`,
                  cursor: "pointer",
                  fontSize: 12,
                  color: t.dangerMuted,
                }}
              >
                <Trash2 size={13} /> Delete
              </button>
            )}
            <button
              onClick={handleSave}
              disabled={isSaving || !toolName.trim()}
              style={{
                padding: "6px 18px",
                borderRadius: 6,
                background: isSaving || !toolName.trim() ? t.surfaceBorder : t.accent,
                border: "none",
                cursor: isSaving || !toolName.trim() ? "default" : "pointer",
                fontSize: 13,
                fontWeight: 600,
                color: "#fff",
                opacity: isSaving || !toolName.trim() ? 0.5 : 1,
              }}
            >
              {isSaving ? "Saving..." : "Save"}
            </button>
          </>
        }
      />

      <ScrollView style={{ flex: 1 }}>
        <div
          style={{
            padding: 20,
            maxWidth: 800,
            margin: "0 auto",
            width: "100%",
            display: "flex",
            flexDirection: "column",
            gap: 24,
          }}
        >
          <Section title="Rule">
            <FormRow
              label="Tool Name"
              description='Exact name or glob pattern. Use "*" for all tools.'
            >
              <TextInput
                value={toolName}
                onChangeText={setToolName}
                placeholder='e.g. exec_command, exec_*, or *'
              />
            </FormRow>
            <FormRow label="Action">
              <SelectInput
                value={action}
                onChange={setAction}
                options={ACTION_OPTIONS}
              />
            </FormRow>
            <FormRow
              label="Bot ID"
              description="Leave empty for a global rule (applies to all bots)"
            >
              <TextInput
                value={botId}
                onChangeText={setBotId}
                placeholder="(global)"
              />
            </FormRow>
            <FormRow
              label="Priority"
              description="Lower number = evaluated first. Bot-specific rules win over global at same priority."
            >
              <TextInput
                value={priority}
                onChangeText={setPriority}
                placeholder="100"
              />
            </FormRow>
            <FormRow label="Reason" description="Human-readable explanation">
              <TextInput
                value={reason}
                onChangeText={setReason}
                placeholder='e.g. "Destructive command"'
              />
            </FormRow>
            <Toggle
              value={enabled}
              onChange={setEnabled}
              label="Enabled"
              description="Disabled rules are skipped during evaluation"
            />
          </Section>

          {action === "require_approval" && (
            <Section title="Approval">
              <FormRow
                label="Timeout (seconds)"
                description="How long to wait for approval before expiring"
              >
                <TextInput
                  value={approvalTimeout}
                  onChangeText={setApprovalTimeout}
                  placeholder="300"
                />
              </FormRow>
            </Section>
          )}

          <Section
            title="Conditions"
            description="JSON argument matchers. Empty = match all calls to this tool."
          >
            <textarea
              value={conditionsJson}
              onChange={(e) => setConditionsJson(e.target.value)}
              rows={6}
              placeholder={'{\n  "arguments": {\n    "command": { "pattern": "^rm " }\n  }\n}'}
              style={{
                background: t.inputBg,
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 8,
                padding: "8px 12px",
                color: t.text,
                fontSize: 13,
                fontFamily: "monospace",
                width: "100%",
                resize: "vertical",
                outline: "none",
              }}
              onFocus={(e) => {
                e.target.style.borderColor = t.accent;
              }}
              onBlur={(e) => {
                e.target.style.borderColor = t.surfaceBorder;
              }}
            />
          </Section>

          {/* Test Panel */}
          <Section title="Test Policy" description="Dry-run to see which rule matches">
            <FormRow label="Bot ID">
              <TextInput
                value={testBotId}
                onChangeText={setTestBotId}
                placeholder="default"
              />
            </FormRow>
            <FormRow label="Tool Name">
              <TextInput
                value={testToolName}
                onChangeText={setTestToolName}
                placeholder={toolName || "exec_command"}
              />
            </FormRow>
            <FormRow label="Arguments (JSON)">
              <TextInput
                value={testArgsJson}
                onChangeText={setTestArgsJson}
                placeholder='{"command": "rm -rf /"}'
              />
            </FormRow>
            <button
              onClick={handleTest}
              disabled={testMut.isPending}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "8px 16px",
                borderRadius: 6,
                background: t.surfaceOverlay,
                border: `1px solid ${t.surfaceBorder}`,
                cursor: "pointer",
                fontSize: 13,
                color: t.text,
                alignSelf: "flex-start",
              }}
            >
              <Play size={13} />
              {testMut.isPending ? "Testing..." : "Test"}
            </button>
            {testResult && (
              <div
                style={{
                  padding: "8px 12px",
                  borderRadius: 6,
                  background: t.surfaceRaised,
                  fontSize: 12,
                  color: t.accent,
                  fontFamily: "monospace",
                }}
              >
                {testResult}
              </div>
            )}
          </Section>

          {!isNew && rule && (
            <Section title="Info">
              <FormRow label="ID">
                <span
                  style={{
                    fontSize: 12,
                    color: t.textDim,
                    fontFamily: "monospace",
                  }}
                >
                  {rule.id}
                </span>
              </FormRow>
              <FormRow label="Created">
                <span style={{ fontSize: 13, color: t.textMuted }}>
                  {new Date(rule.created_at).toLocaleString()}
                </span>
              </FormRow>
              <FormRow label="Updated">
                <span style={{ fontSize: 13, color: t.textMuted }}>
                  {new Date(rule.updated_at).toLocaleString()}
                </span>
              </FormRow>
            </Section>
          )}
        </div>
      </ScrollView>
    </View>
  );
}
