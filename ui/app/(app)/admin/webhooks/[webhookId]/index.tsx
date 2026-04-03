import { useState, useCallback } from "react";
import { View, ScrollView, ActivityIndicator } from "react-native";
import { useLocalSearchParams } from "expo-router";
import {
  ChevronLeft,
  Trash2,
  Copy,
  Check,
  AlertTriangle,
  RefreshCw,
  Send,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { writeToClipboard } from "@/src/utils/clipboard";
import { useGoBack } from "@/src/hooks/useGoBack";
import {
  useWebhook,
  useWebhookEvents,
  useCreateWebhook,
  useUpdateWebhook,
  useDeleteWebhook,
  useRotateWebhookSecret,
  useTestWebhook,
  useWebhookDeliveries,
  type WebhookDeliveryItem,
  type WebhookTestResult,
} from "@/src/api/hooks/useWebhooks";
import {
  Section,
  FormRow,
  TextInput,
  Toggle,
} from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";

function EventCheckboxGrid({
  events,
  selected,
  onChange,
}: {
  events: { event: string; description: string }[];
  selected: string[];
  onChange: (events: string[]) => void;
}) {
  const t = useThemeTokens();
  const set = new Set(selected);

  const toggle = (event: string) => {
    const next = new Set(set);
    if (next.has(event)) next.delete(event);
    else next.add(event);
    onChange(Array.from(next));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ fontSize: 11, color: t.textDim, marginBottom: 4 }}>
        Leave all unchecked to receive all events.
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {events.map((ev) => {
          const checked = set.has(ev.event);
          return (
            <button
              key={ev.event}
              onClick={() => toggle(ev.event)}
              title={ev.description}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "4px 10px",
                borderRadius: 5,
                border: checked
                  ? `1px solid ${t.accentBorder}`
                  : `1px solid ${t.surfaceBorder}`,
                background: checked ? t.accentSubtle : "transparent",
                cursor: "pointer",
                fontSize: 12,
                color: checked ? t.accent : t.textDim,
                fontWeight: checked ? 600 : 400,
              }}
            >
              <span
                style={{
                  width: 14,
                  height: 14,
                  borderRadius: 3,
                  border: checked ? "none" : `1px solid ${t.surfaceBorder}`,
                  background: checked ? t.accent : "transparent",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {checked && <Check size={10} color="#fff" strokeWidth={3} />}
              </span>
              {ev.event}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StatusDot({ code }: { code: number | null }) {
  const t = useThemeTokens();
  const ok = code !== null && code >= 200 && code < 300;
  return (
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: 4,
        background: code === null ? t.textDim : ok ? t.success : t.danger,
        display: "inline-block",
      }}
    />
  );
}

function DeliveryRow({ delivery }: { delivery: WebhookDeliveryItem }) {
  const t = useThemeTokens();
  const time = new Date(delivery.created_at).toLocaleString();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 0",
        borderBottom: `1px solid ${t.surfaceOverlay}`,
        fontSize: 12,
      }}
    >
      <StatusDot code={delivery.status_code} />
      <span
        style={{
          fontFamily: "monospace",
          color: t.accent,
          minWidth: 120,
        }}
      >
        {delivery.event}
      </span>
      <span style={{ color: t.textMuted, minWidth: 50, textAlign: "center" }}>
        {delivery.status_code ?? "err"}
      </span>
      <span style={{ color: t.textDim, minWidth: 30, textAlign: "right" }}>
        ×{delivery.attempt}
      </span>
      <span style={{ color: t.textDim, minWidth: 50, textAlign: "right" }}>
        {delivery.duration_ms != null ? `${delivery.duration_ms}ms` : "—"}
      </span>
      <span style={{ flex: 1, color: t.textDim, textAlign: "right" }}>
        {time}
      </span>
      {delivery.error && (
        <span
          style={{
            color: t.danger,
            maxWidth: 200,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={delivery.error}
        >
          {delivery.error}
        </span>
      )}
    </div>
  );
}

export default function WebhookDetailScreen() {
  const t = useThemeTokens();
  const { webhookId } = useLocalSearchParams<{ webhookId: string }>();
  const isNew = webhookId === "new";
  const goBack = useGoBack("/admin/webhooks");

  const { data: webhook, isLoading } = useWebhook(isNew ? undefined : webhookId);
  const { data: eventTypes } = useWebhookEvents();
  const createMut = useCreateWebhook();
  const updateMut = useUpdateWebhook(webhookId);
  const deleteMut = useDeleteWebhook();
  const rotateMut = useRotateWebhookSecret(webhookId);
  const testMut = useTestWebhook(webhookId);
  const { data: deliveries, isLoading: deliveriesLoading } = useWebhookDeliveries(
    isNew ? undefined : webhookId,
    { limit: 20 },
  );

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [events, setEvents] = useState<string[]>([]);
  const [isActive, setIsActive] = useState(true);
  const [initialized, setInitialized] = useState(isNew);

  // Secret reveal states
  const [createdSecret, setCreatedSecret] = useState<string | null>(null);
  const [rotatedSecret, setRotatedSecret] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Test result
  const [testResult, setTestResult] = useState<WebhookTestResult | null>(null);

  // Initialize from loaded data
  if (webhook && !initialized) {
    setName(webhook.name);
    setUrl(webhook.url);
    setDescription(webhook.description);
    setEvents(webhook.events);
    setIsActive(webhook.is_active);
    setInitialized(true);
  }

  const isSaving = createMut.isPending || updateMut.isPending;

  const handleSave = useCallback(async () => {
    if (isNew) {
      const result = await createMut.mutateAsync({
        name: name.trim(),
        url: url.trim(),
        events,
        is_active: isActive,
        description: description.trim(),
      });
      setCreatedSecret(result.secret);
    } else {
      await updateMut.mutateAsync({
        name: name.trim(),
        url: url.trim(),
        events,
        is_active: isActive,
        description: description.trim(),
      });
    }
  }, [isNew, name, url, events, isActive, description, createMut, updateMut]);

  const handleDelete = useCallback(async () => {
    if (!confirm("Delete this webhook endpoint? All delivery history will be lost."))
      return;
    await deleteMut.mutateAsync(webhookId!);
    goBack();
  }, [webhookId, deleteMut, goBack]);

  const handleRotate = useCallback(async () => {
    if (!confirm("Rotate the signing secret? The old secret will stop working immediately."))
      return;
    const result = await rotateMut.mutateAsync();
    setRotatedSecret(result.secret);
  }, [rotateMut]);

  const handleTest = useCallback(async () => {
    setTestResult(null);
    const result = await testMut.mutateAsync();
    setTestResult(result);
  }, [testMut]);

  const handleCopy = useCallback(
    async (text: string) => {
      await writeToClipboard(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    },
    [],
  );

  if (!isNew && isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  const displaySecret = createdSecret || rotatedSecret;

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "12px 20px",
          borderBottom: `1px solid ${t.surfaceOverlay}`,
        }}
      >
        <button
          onClick={goBack}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 4 }}
        >
          <ChevronLeft size={22} color={t.textMuted} />
        </button>
        <span style={{ flex: 1, fontSize: 16, fontWeight: 600, color: t.text }}>
          {isNew ? "New Webhook" : "Edit Webhook"}
        </span>
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
          onClick={createdSecret ? goBack : handleSave}
          disabled={!createdSecret && (isSaving || !name.trim() || !url.trim())}
          style={{
            padding: "6px 18px",
            borderRadius: 6,
            background:
              !createdSecret && (isSaving || !name.trim() || !url.trim())
                ? t.surfaceBorder
                : t.accent,
            border: "none",
            cursor:
              !createdSecret && (isSaving || !name.trim() || !url.trim())
                ? "default"
                : "pointer",
            fontSize: 13,
            fontWeight: 600,
            color: "#fff",
            opacity:
              !createdSecret && (isSaving || !name.trim() || !url.trim()) ? 0.5 : 1,
          }}
        >
          {isSaving ? "Saving..." : createdSecret ? "Done" : "Save"}
        </button>
      </div>

      <ScrollView style={{ flex: 1 }}>
        <div style={{ padding: 20, maxWidth: 800, margin: "0 auto", width: "100%" }}>
          {/* Secret reveal */}
          {displaySecret && (
            <div
              style={{
                padding: 16,
                borderRadius: 10,
                background: t.successSubtle,
                border: `1px solid ${t.successBorder}`,
                marginBottom: 20,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 8,
                }}
              >
                <AlertTriangle size={14} color={t.warningMuted} />
                <span style={{ fontSize: 13, fontWeight: 600, color: t.warningMuted }}>
                  {createdSecret
                    ? "Save this signing secret now. It won't be shown again."
                    : "New signing secret generated. Save it now."}
                </span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <code
                  style={{
                    flex: 1,
                    padding: "8px 12px",
                    borderRadius: 6,
                    background: t.surfaceRaised,
                    fontSize: 12,
                    color: t.success,
                    wordBreak: "break-all",
                    fontFamily: "monospace",
                  }}
                >
                  {displaySecret}
                </code>
                <button
                  onClick={() => handleCopy(displaySecret)}
                  style={{
                    padding: "8px 12px",
                    borderRadius: 6,
                    background: t.surfaceOverlay,
                    border: `1px solid ${t.surfaceBorder}`,
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 12,
                    color: copied ? t.success : t.textMuted,
                  }}
                >
                  {copied ? <Check size={13} /> : <Copy size={13} />}
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
            </div>
          )}

          <Section title="Identity">
            <FormRow label="Name">
              <TextInput
                value={name}
                onChangeText={setName}
                placeholder="e.g. my-monitoring-service"
              />
            </FormRow>
            <FormRow label="URL">
              <TextInput
                value={url}
                onChangeText={setUrl}
                placeholder="https://example.com/webhooks/spindrel"
              />
            </FormRow>
            <FormRow label="Description" description="Optional note about this endpoint">
              <TextInput
                value={description}
                onChangeText={setDescription}
                placeholder="Receives tool call events for monitoring"
              />
            </FormRow>
            <Toggle
              value={isActive}
              onChange={setIsActive}
              label="Active"
              description="Inactive endpoints stop receiving events"
            />
          </Section>

          {/* Secret management (edit only) */}
          {!isNew && !rotatedSecret && (
            <Section title="Signing Secret">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 13, color: t.textDim, flex: 1 }}>
                  The signing secret is used to verify webhook payloads via HMAC-SHA256.
                </span>
                <button
                  onClick={handleRotate}
                  disabled={rotateMut.isPending}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "6px 12px",
                    borderRadius: 6,
                    background: t.surfaceOverlay,
                    border: `1px solid ${t.surfaceBorder}`,
                    cursor: rotateMut.isPending ? "default" : "pointer",
                    fontSize: 12,
                    color: t.textMuted,
                    opacity: rotateMut.isPending ? 0.5 : 1,
                  }}
                >
                  <RefreshCw size={12} />
                  {rotateMut.isPending ? "Rotating..." : "Rotate Secret"}
                </button>
              </div>
            </Section>
          )}

          <Section title="Events">
            {eventTypes ? (
              <EventCheckboxGrid
                events={eventTypes}
                selected={events}
                onChange={setEvents}
              />
            ) : (
              <ActivityIndicator color={t.accent} />
            )}
          </Section>

          {/* Test section (edit only) */}
          {!isNew && (
            <Section title="Test">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <button
                  onClick={handleTest}
                  disabled={testMut.isPending}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    padding: "6px 14px",
                    borderRadius: 6,
                    background: t.accent,
                    border: "none",
                    cursor: testMut.isPending ? "default" : "pointer",
                    fontSize: 13,
                    fontWeight: 600,
                    color: "#fff",
                    opacity: testMut.isPending ? 0.5 : 1,
                  }}
                >
                  <Send size={13} />
                  {testMut.isPending ? "Sending..." : "Send Test Event"}
                </button>
              </div>
              {testResult && (
                <div
                  style={{
                    marginTop: 12,
                    padding: 12,
                    borderRadius: 8,
                    background: testResult.success ? t.successSubtle : t.dangerSubtle,
                    border: `1px solid ${testResult.success ? t.successBorder : t.dangerBorder}`,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 12,
                  }}
                >
                  {testResult.success ? (
                    <CheckCircle2 size={14} color={t.success} />
                  ) : (
                    <XCircle size={14} color={t.danger} />
                  )}
                  <span style={{ color: testResult.success ? t.success : t.danger }}>
                    {testResult.success
                      ? `Success — ${testResult.status_code} in ${testResult.duration_ms}ms`
                      : testResult.error
                        ? `Failed — ${testResult.error}`
                        : `Failed — HTTP ${testResult.status_code}`}
                  </span>
                </div>
              )}
            </Section>
          )}

          {/* Delivery log (edit only) */}
          {!isNew && (
            <Section title="Recent Deliveries">
              {deliveriesLoading ? (
                <View className="items-center py-4">
                  <ActivityIndicator color={t.accent} />
                </View>
              ) : deliveries && deliveries.length > 0 ? (
                <div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      padding: "6px 0",
                      fontSize: 10,
                      fontWeight: 600,
                      color: t.textDim,
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                      borderBottom: `1px solid ${t.surfaceOverlay}`,
                    }}
                  >
                    <span style={{ width: 8 }} />
                    <span style={{ minWidth: 120 }}>Event</span>
                    <span style={{ minWidth: 50, textAlign: "center" }}>Status</span>
                    <span style={{ minWidth: 30, textAlign: "right" }}>Try</span>
                    <span style={{ minWidth: 50, textAlign: "right" }}>Time</span>
                    <span style={{ flex: 1, textAlign: "right" }}>Date</span>
                  </div>
                  {deliveries.map((d) => (
                    <DeliveryRow key={d.id} delivery={d} />
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 13, color: t.textDim, padding: "8px 0" }}>
                  No deliveries yet. Send a test event to see delivery history.
                </div>
              )}
            </Section>
          )}

          {/* Info (edit only) */}
          {!isNew && webhook && (
            <Section title="Info">
              <FormRow label="Created">
                <span style={{ fontSize: 13, color: t.textMuted }}>
                  {new Date(webhook.created_at).toLocaleString()}
                </span>
              </FormRow>
              <FormRow label="Updated">
                <span style={{ fontSize: 13, color: t.textMuted }}>
                  {new Date(webhook.updated_at).toLocaleString()}
                </span>
              </FormRow>
            </Section>
          )}
        </div>
      </ScrollView>
    </View>
  );
}
