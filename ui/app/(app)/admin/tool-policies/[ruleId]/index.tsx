import { Spinner } from "@/src/components/shared/Spinner";
import { useState, useCallback } from "react";

import { useParams } from "react-router-dom";
import { Trash2, Play } from "lucide-react";
import { useGoBack } from "@/src/hooks/useGoBack";
import { PageHeader } from "@/src/components/layout/PageHeader";
import {
  useToolPolicies,
  useCreateToolPolicy,
  useUpdateToolPolicy,
  useDeleteToolPolicy,
  useTestToolPolicy,
  ruleAppliesToAutonomous,
  AUTONOMOUS_ORIGINS,
} from "@/src/api/hooks/useToolPolicies";
import {
  Section,
  FormRow,
  TextInput,
  SelectInput,
  Toggle,
} from "@/src/components/shared/FormControls";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { useThemeTokens } from "@/src/theme/tokens";

const ACTION_OPTIONS = [
  { label: "Allow", value: "allow" },
  { label: "Deny", value: "deny" },
  { label: "Require Approval", value: "require_approval" },
];

export default function ToolPolicyDetailScreen() {
  const t = useThemeTokens();
  const params = useParams<{ ruleId: string; bot_id?: string }>();
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
  const [applyToAutonomous, setApplyToAutonomous] = useState(false);
  const [approvalTimeout, setApprovalTimeout] = useState("300");
  const [conditionsJson, setConditionsJson] = useState("{}");
  const [initialized, setInitialized] = useState(isNew);
  const { confirm, ConfirmDialogSlot } = useConfirm();

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
    setApplyToAutonomous(ruleAppliesToAutonomous(rule));
    setApprovalTimeout(String(rule.approval_timeout));
    // Strip the origin_kind matcher from the JSON view — the toggle is
    // the canonical surface. Manual JSON edits to origin_kind still apply
    // server-side; the toggle just covers the common case.
    const conditionsForDisplay = { ...(rule.conditions || {}) };
    delete (conditionsForDisplay as Record<string, unknown>).origin_kind;
    setConditionsJson(JSON.stringify(conditionsForDisplay, null, 2));
    setInitialized(true);
  }

  const isSaving = createMut.isPending || updateMut.isPending;

  const handleSave = useCallback(async () => {
    let conditions: Record<string, any> = {};
    try {
      conditions = JSON.parse(conditionsJson);
    } catch {
      alert("Invalid JSON in conditions");
      return;
    }

    // Toggle drives the origin_kind matcher. ON → matches autonomous origins
    // (rule applies to interactive AND autonomous runs because backend ORs
    // origin matchers). OFF → matcher is removed; backend default treats the
    // rule as interactive-only.
    if (applyToAutonomous) {
      conditions.origin_kind = { in: [...AUTONOMOUS_ORIGINS] };
    } else {
      delete conditions.origin_kind;
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
    applyToAutonomous,
    approvalTimeout,
    conditionsJson,
    createMut,
    updateMut,
    goBack,
  ]);

  const handleDelete = useCallback(async () => {
    const ok = await confirm("Delete this policy rule?", {
      title: "Delete policy",
      confirmLabel: "Delete",
      variant: "danger",
    });
    if (!ok) return;
    await deleteMut.mutateAsync(ruleId!);
    goBack();
  }, [ruleId, deleteMut, goBack, confirm]);

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
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="detail"
        parentLabel="Tool Policies"
        backTo="/admin/tool-policies"
        title={isNew ? "New Policy Rule" : "Edit Policy Rule"}
        right={
          <>
            {!isNew && (
              <button
                onClick={handleDelete}
                style={{
                  display: "flex", flexDirection: "row",
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

      <div style={{ flex: 1 }}>
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
            <Toggle
              value={applyToAutonomous}
              onChange={setApplyToAutonomous}
              label="Apply to autonomous runs"
              description="Heartbeat / scheduled task / subagent / hygiene origins. Off (default) keeps the rule interactive-only."
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
                display: "flex", flexDirection: "row",
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
      </div>
      <ConfirmDialogSlot />
    </div>
  );
}
