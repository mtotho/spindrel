import { useState, useCallback, useRef, useEffect } from "react";
import { View, Text, ActivityIndicator, Pressable, Platform, Animated } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Check, ChevronDown, ChevronRight, Download, Upload, ShieldAlert } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { writeToClipboard } from "@/src/utils/clipboard";

const SENSITIVE_KEY_PATTERN = /api[_-]?key|secret|token|password|credential|auth[_-]?header/i;

function redactSecrets(obj: any): any {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) return obj.map(redactSecrets);
  if (typeof obj === "object") {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (SENSITIVE_KEY_PATTERN.test(k) && v != null && v !== "" && typeof v !== "object") {
        out[k] = "***REDACTED***";
      } else {
        out[k] = redactSecrets(v);
      }
    }
    return out;
  }
  return obj;
}

function countRedacted(original: any, redacted: any): number {
  if (original === null || original === undefined || typeof original !== "object") return 0;
  if (Array.isArray(original)) {
    return original.reduce((sum, item, i) => sum + countRedacted(item, redacted?.[i]), 0);
  }
  let count = 0;
  for (const k of Object.keys(original)) {
    if (redacted?.[k] === "***REDACTED***" && original[k] !== "***REDACTED***") {
      count++;
    } else {
      count += countRedacted(original[k], redacted?.[k]);
    }
  }
  return count;
}

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  const t = useThemeTokens();
  const opacity = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(opacity, { toValue: 1, duration: 200, useNativeDriver: true }).start();
    const timer = setTimeout(() => {
      Animated.timing(opacity, { toValue: 0, duration: 300, useNativeDriver: true }).start(() => onDismiss());
    }, 4000);
    return () => clearTimeout(timer);
  }, [onDismiss, opacity]);
  return (
    <Animated.View
      style={{
        position: "absolute",
        bottom: 24,
        left: 16,
        right: 16,
        maxWidth: 480,
        alignSelf: "center",
        opacity,
        backgroundColor: t.warning,
        borderRadius: 8,
        padding: 12,
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        zIndex: 100,
      }}
    >
      <ShieldAlert size={16} color="#000" />
      <Text style={{ fontSize: 12, color: "#000", flex: 1 }}>{message}</Text>
    </Animated.View>
  );
}

function useConfigState() {
  return useQuery({
    queryKey: ["config-state"],
    queryFn: () => apiFetch<Record<string, any>>("/api/v1/admin/config-state"),
  });
}

function CollapsibleSection({
  title,
  badge,
  children,
  defaultOpen = false,
}: {
  title: string;
  badge?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <View style={{ marginBottom: 2 }}>
      <Pressable
        onPress={() => setOpen((p) => !p)}
        className="flex-row items-center gap-2 rounded-md px-3 py-2.5 hover:bg-surface-overlay active:bg-surface-overlay"
      >
        <Icon size={14} color={t.textMuted} />
        <Text style={{ fontSize: 13, fontWeight: "600", color: t.text }}>
          {title}
        </Text>
        {badge ? (
          <Text style={{ fontSize: 11, color: t.textDim, marginLeft: 4 }}>
            {badge}
          </Text>
        ) : null}
      </Pressable>
      {open ? (
        <View style={{ paddingLeft: 24, paddingBottom: 8 }}>{children}</View>
      ) : null}
    </View>
  );
}

function KV({ k, v }: { k: string; v: any }) {
  const t = useThemeTokens();
  const display =
    v === null || v === undefined
      ? "null"
      : typeof v === "boolean"
        ? v
          ? "true"
          : "false"
        : typeof v === "object"
          ? JSON.stringify(v)
          : String(v);
  return (
    <View className="flex-row" style={{ paddingVertical: 1 }}>
      <Text
        style={{
          fontSize: 12,
          color: t.textMuted,
          fontFamily: "monospace",
          minWidth: 200,
        }}
        numberOfLines={1}
      >
        {k}
      </Text>
      <Text
        style={{
          fontSize: 12,
          color: t.text,
          fontFamily: "monospace",
          flex: 1,
        }}
        numberOfLines={2}
      >
        {display}
      </Text>
    </View>
  );
}

function DetailJSON({ data }: { data: any }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  if (!expanded) {
    return (
      <Pressable onPress={() => setExpanded(true)}>
        <Text style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
          {"{ ... }"}
        </Text>
      </Pressable>
    );
  }
  return (
    <Pressable onPress={() => setExpanded(false)}>
      <Text
        style={{ fontSize: 11, color: "#777", fontFamily: "monospace" }}
        selectable
      >
        {JSON.stringify(data, null, 2)}
      </Text>
    </Pressable>
  );
}

function SystemSection({ data }: { data: Record<string, any> }) {
  return (
    <>
      {Object.entries(data).map(([k, v]) => (
        <KV key={k} k={k} v={v} />
      ))}
    </>
  );
}

function SettingsSection({ data }: { data: Record<string, Record<string, any>> }) {
  return (
    <>
      {Object.entries(data).map(([group, settings]) => (
        <CollapsibleSection key={group} title={group} badge={`${Object.keys(settings).length}`}>
          {Object.entries(settings).map(([k, v]) => (
            <KV key={k} k={k} v={v} />
          ))}
        </CollapsibleSection>
      ))}
    </>
  );
}

function ProvidersSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((p) => (
        <View key={p.id} style={{ marginBottom: 4 }}>
          <View className="flex-row items-center gap-2" style={{ paddingVertical: 2 }}>
            <Text style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
              {p.display_name}
            </Text>
            <Text style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {p.provider_type}
            </Text>
            <Text style={{ fontSize: 11, color: p.is_enabled ? t.success : t.danger, fontFamily: "monospace" }}>
              {p.is_enabled ? "enabled" : "disabled"}
            </Text>
            <Text style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {p.models.length} models
            </Text>
          </View>
          <DetailJSON data={p} />
        </View>
      ))}
    </>
  );
}

function BotsSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((b) => (
        <View key={b.id} style={{ marginBottom: 6 }}>
          <View className="flex-row items-center gap-2 flex-wrap" style={{ paddingVertical: 2 }}>
            <Text style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
              {b.name}
            </Text>
            <Text style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
              {b.model}
            </Text>
          </View>
          <View className="flex-row flex-wrap gap-x-3" style={{ paddingVertical: 1 }}>
            <Tag label="tools" value={b.local_tools?.length ?? 0} />
            <Tag label="mcp" value={b.mcp_servers?.length ?? 0} />
            <Tag label="skills" value={b.skills?.length ?? 0} />
            <Tag label="memory" value={b.memory_config?.enabled ? "on" : "off"} on={b.memory_config?.enabled} />
            <Tag label="knowledge" value={b.knowledge_config?.enabled ? "on" : "off"} on={b.knowledge_config?.enabled} />
            <Tag label="compaction" value={b.context_compaction ? "on" : "off"} on={b.context_compaction} />
          </View>
          <DetailJSON data={b} />
        </View>
      ))}
    </>
  );
}

function Tag({ label, value, on }: { label: string; value: any; on?: boolean }) {
  const t = useThemeTokens();
  return (
    <Text style={{ fontSize: 11, color: on ? t.accent : t.textDim, fontFamily: "monospace" }}>
      {label}:{String(value)}
    </Text>
  );
}

function ChannelsSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((ch) => (
        <View key={ch.id} style={{ marginBottom: 4 }}>
          <View className="flex-row items-center gap-2" style={{ paddingVertical: 2 }}>
            <Text style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
              {ch.name}
            </Text>
            <Text style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
              bot:{ch.bot_id}
            </Text>
            {ch.integration && (
              <Text style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
                {ch.integration}
              </Text>
            )}
          </View>
          <DetailJSON data={ch} />
        </View>
      ))}
    </>
  );
}

function WorkspacesSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((ws) => (
        <View key={ws.id} style={{ marginBottom: 4 }}>
          <View className="flex-row items-center gap-2" style={{ paddingVertical: 2 }}>
            <Text style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
              {ws.name}
            </Text>
            <Text style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
              {ws.image}
            </Text>
            <Text
              style={{
                fontSize: 11,
                color: ws.status === "running" ? t.success : t.textDim,
                fontFamily: "monospace",
              }}
            >
              {ws.status}
            </Text>
            <Text style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {ws.bots?.length ?? 0} bots
            </Text>
          </View>
          <DetailJSON data={ws} />
        </View>
      ))}
    </>
  );
}

function SkillsSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((s) => (
        <View key={s.id} className="flex-row items-center gap-3" style={{ paddingVertical: 2 }}>
          <Text style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600", minWidth: 160 }}>
            {s.name}
          </Text>
          <Text style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {s.source_type}
          </Text>
          <Text style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
            {s.chunk_count} chunks
          </Text>
        </View>
      ))}
    </>
  );
}

function TasksSection({ data }: { data: any[] }) {
  const tk = useThemeTokens();
  if (data.length === 0) {
    return <Text style={{ fontSize: 12, color: tk.textDim, fontFamily: "monospace" }}>No recurring tasks</Text>;
  }
  return (
    <>
      {data.map((t) => (
        <View key={t.id} className="flex-row items-center gap-3" style={{ paddingVertical: 2 }}>
          <Text style={{ fontSize: 12, color: tk.text, fontFamily: "monospace", fontWeight: "600" }}>
            {t.title || t.bot_id}
          </Text>
          <Text style={{ fontSize: 11, color: tk.textMuted, fontFamily: "monospace" }}>
            {t.task_type}
          </Text>
          {t.recurrence && (
            <Text style={{ fontSize: 11, color: tk.accent, fontFamily: "monospace" }}>
              every {t.recurrence}
            </Text>
          )}
          <Text
            style={{
              fontSize: 11,
              color: t.status === "running" ? tk.success : t.status === "pending" ? tk.warning : tk.textDim,
              fontFamily: "monospace",
            }}
          >
            {t.status}
          </Text>
        </View>
      ))}
    </>
  );
}

function UsersSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((u) => (
        <View key={u.id} className="flex-row items-center gap-3" style={{ paddingVertical: 2 }}>
          <Text style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
            {u.display_name}
          </Text>
          <Text style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {u.email}
          </Text>
          <Text style={{ fontSize: 11, color: u.is_admin ? t.accent : t.textDim, fontFamily: "monospace" }}>
            {u.is_admin ? "admin" : "user"}
          </Text>
          {!u.is_active && (
            <Text style={{ fontSize: 11, color: t.danger, fontFamily: "monospace" }}>
              inactive
            </Text>
          )}
        </View>
      ))}
    </>
  );
}

function GenericListSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  if (data.length === 0) {
    return <Text style={{ fontSize: 12, color: t.textDim, fontFamily: "monospace" }}>None</Text>;
  }
  return (
    <>
      {data.map((item, i) => (
        <View key={item.id ?? item.bot_id ?? i} style={{ marginBottom: 4 }}>
          <DetailJSON data={item} />
        </View>
      ))}
    </>
  );
}

function downloadJson(data: any, filename: string) {
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function ConfigStatePage() {
  const t = useThemeTokens();
  const { data, isLoading, error } = useConfigState();
  const queryClient = useQueryClient();
  const { refreshing, onRefresh } = usePageRefresh();
  const [copied, setCopied] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [restoreResult, setRestoreResult] = useState<{ status: string; summary: Record<string, any> } | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [confirmPayload, setConfirmPayload] = useState<Record<string, any> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleCopy = useCallback(async () => {
    if (!data) return;
    try {
      const redacted = redactSecrets(data);
      const n = countRedacted(data, redacted);
      await writeToClipboard(JSON.stringify(redacted, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      if (n > 0) {
        setToastMessage(
          `${n} secret${n > 1 ? "s" : ""} redacted from clipboard. Use Backup to export with secrets.`
        );
      }
    } catch {
      // fallback: noop
    }
  }, [data]);

  const handleBackup = useCallback(() => {
    if (!data) return;
    const date = new Date().toISOString().slice(0, 10);
    downloadJson(data, `config-backup-${date}.json`);
  }, [data]);

  const handleFileSelect = useCallback(() => {
    if (Platform.OS !== "web") return;
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      setConfirmPayload(payload);
      setRestoreError(null);
      setRestoreResult(null);
    } catch {
      setRestoreError("Invalid JSON file");
    }
    // Reset file input so same file can be selected again
    e.target.value = "";
  }, []);

  const handleRestore = useCallback(async () => {
    if (!confirmPayload) return;
    setRestoring(true);
    setRestoreError(null);
    setRestoreResult(null);
    try {
      const result = await apiFetch<{ status: string; summary: Record<string, any> }>(
        "/api/v1/admin/config-state/restore",
        { method: "POST", body: JSON.stringify(confirmPayload) }
      );
      setRestoreResult(result);
      setConfirmPayload(null);
      // Refresh the config state data
      queryClient.invalidateQueries({ queryKey: ["config-state"] });
    } catch (err: any) {
      setRestoreError(err?.message || "Restore failed");
    } finally {
      setRestoring(false);
    }
  }, [confirmPayload, queryClient]);

  const handleCancelRestore = useCallback(() => {
    setConfirmPayload(null);
    setRestoreError(null);
  }, []);

  const HeaderButtons = (
    <View className="flex-row items-center gap-1">
      <Pressable
        onPress={handleBackup}
        disabled={!data}
        className="flex-row items-center gap-1.5 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay"
        style={{ opacity: data ? 1 : 0.4 }}
      >
        <Download size={14} color={t.accent} />
        <Text style={{ fontSize: 12, color: t.accent }}>Backup</Text>
      </Pressable>
      <Pressable
        onPress={handleFileSelect}
        className="flex-row items-center gap-1.5 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay"
      >
        <Upload size={14} color={t.warning} />
        <Text style={{ fontSize: 12, color: t.warning }}>Restore</Text>
      </Pressable>
      <Pressable
        onPress={handleCopy}
        disabled={!data}
        className="flex-row items-center gap-1.5 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay"
        style={{ opacity: data ? 1 : 0.4 }}
      >
        {copied ? <Check size={14} color={t.success} /> : <Copy size={14} color={t.textMuted} />}
        <Text style={{ fontSize: 12, color: copied ? t.success : t.textMuted }}>
          {copied ? "Copied" : "Copy"}
        </Text>
      </Pressable>
    </View>
  );

  // Count sections in confirm payload
  const confirmSections = confirmPayload
    ? Object.entries(confirmPayload)
        .filter(([, v]) => Array.isArray(v) && v.length > 0)
        .map(([k, v]) => `${k}: ${(v as any[]).length}`)
    : [];

  return (
    <View style={{ flex: 1, backgroundColor: t.surface }}>
      {/* Hidden file input for restore */}
      {Platform.OS === "web" && (
        <input
          ref={fileInputRef as any}
          type="file"
          accept=".json"
          style={{ display: "none" }}
          onChange={handleFileChange as any}
        />
      )}

      <MobileHeader title="Config State" right={HeaderButtons} />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, maxWidth: 960 }}
      >
        {/* Restore confirmation dialog */}
        {confirmPayload && (
          <View
            style={{
              backgroundColor: t.surfaceRaised,
              borderRadius: 8,
              padding: 16,
              marginBottom: 16,
              borderWidth: 1,
              borderColor: t.warning,
            }}
          >
            <Text style={{ fontSize: 14, fontWeight: "600", color: t.warning, marginBottom: 8 }}>
              Confirm Restore
            </Text>
            <Text style={{ fontSize: 12, color: t.text, marginBottom: 8 }}>
              This will upsert the following sections:
            </Text>
            {confirmSections.map((s) => (
              <Text key={s} style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace", paddingLeft: 8 }}>
                {s}
              </Text>
            ))}
            <View className="flex-row gap-3" style={{ marginTop: 12 }}>
              <Pressable
                onPress={handleRestore}
                disabled={restoring}
                style={{
                  backgroundColor: t.warning,
                  paddingHorizontal: 16,
                  paddingVertical: 6,
                  borderRadius: 6,
                  opacity: restoring ? 0.5 : 1,
                }}
              >
                <Text style={{ fontSize: 12, fontWeight: "600", color: "#000" }}>
                  {restoring ? "Restoring..." : "Confirm Restore"}
                </Text>
              </Pressable>
              <Pressable
                onPress={handleCancelRestore}
                disabled={restoring}
                style={{
                  paddingHorizontal: 16,
                  paddingVertical: 6,
                  borderRadius: 6,
                  borderWidth: 1,
                  borderColor: t.textDim,
                }}
              >
                <Text style={{ fontSize: 12, color: t.textMuted }}>Cancel</Text>
              </Pressable>
            </View>
          </View>
        )}

        {/* Restore result */}
        {restoreResult && (
          <View
            style={{
              backgroundColor: t.successSubtle,
              borderRadius: 8,
              padding: 16,
              marginBottom: 16,
              borderWidth: 1,
              borderColor: t.success,
            }}
          >
            <Text style={{ fontSize: 13, fontWeight: "600", color: t.success, marginBottom: 8 }}>
              Restore Complete
            </Text>
            {Object.entries(restoreResult.summary).map(([section, counts]) => (
              <Text key={section} style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace", paddingLeft: 8 }}>
                {section}: {(counts as any).updated ?? 0} upserted
              </Text>
            ))}
            <Pressable onPress={() => setRestoreResult(null)} style={{ marginTop: 8 }}>
              <Text style={{ fontSize: 11, color: t.textDim }}>Dismiss</Text>
            </Pressable>
          </View>
        )}

        {/* Restore error */}
        {restoreError && (
          <View
            style={{
              backgroundColor: t.dangerSubtle,
              borderRadius: 8,
              padding: 12,
              marginBottom: 16,
              borderWidth: 1,
              borderColor: t.danger,
            }}
          >
            <Text style={{ fontSize: 12, color: t.danger }}>{restoreError}</Text>
            <Pressable onPress={() => setRestoreError(null)} style={{ marginTop: 4 }}>
              <Text style={{ fontSize: 11, color: t.textDim }}>Dismiss</Text>
            </Pressable>
          </View>
        )}

        {isLoading ? (
          <View style={{ padding: 40, alignItems: "center" }}>
            <ActivityIndicator color={t.accent} />
          </View>
        ) : error ? (
          <Text style={{ color: t.danger, fontSize: 13 }}>
            Failed to load config state
          </Text>
        ) : data ? (
          <View style={{ gap: 2 }}>
            <CollapsibleSection title="System" defaultOpen>
              <SystemSection data={data.system} />
            </CollapsibleSection>

            <CollapsibleSection
              title="Global Fallback Models"
              badge={`${data.global_fallback_models?.length ?? 0}`}
            >
              {(data.global_fallback_models || []).length === 0 ? (
                <Text style={{ fontSize: 12, color: t.textDim, fontFamily: "monospace" }}>
                  None configured
                </Text>
              ) : (
                data.global_fallback_models.map((m: any, i: number) => (
                  <KV key={i} k={`[${i}]`} v={m.model || JSON.stringify(m)} />
                ))
              )}
            </CollapsibleSection>

            <CollapsibleSection
              title="Settings"
              badge={`${Object.keys(data.settings || {}).length} groups`}
            >
              <SettingsSection data={data.settings} />
            </CollapsibleSection>

            <CollapsibleSection title="Providers" badge={`${data.providers?.length ?? 0}`}>
              <ProvidersSection data={data.providers || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Bots" badge={`${data.bots?.length ?? 0}`}>
              <BotsSection data={data.bots || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Channels" badge={`${data.channels?.length ?? 0}`}>
              <ChannelsSection data={data.channels || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Workspaces" badge={`${data.workspaces?.length ?? 0}`}>
              <WorkspacesSection data={data.workspaces || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Skills" badge={`${data.skills?.length ?? 0}`}>
              <SkillsSection data={data.skills || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Tasks" badge={`${data.tasks?.length ?? 0}`}>
              <TasksSection data={data.tasks || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Users" badge={`${data.users?.length ?? 0}`}>
              <UsersSection data={data.users || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Sandbox Profiles" badge={`${data.sandbox_profiles?.length ?? 0}`}>
              <GenericListSection data={data.sandbox_profiles || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Sandbox Bot Access" badge={`${data.sandbox_bot_access?.length ?? 0}`}>
              <GenericListSection data={data.sandbox_bot_access || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Tool Policy Rules" badge={`${data.tool_policy_rules?.length ?? 0}`}>
              <GenericListSection data={data.tool_policy_rules || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Prompt Templates" badge={`${data.prompt_templates?.length ?? 0}`}>
              <GenericListSection data={data.prompt_templates || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Bot Personas" badge={`${data.bot_personas?.length ?? 0}`}>
              <GenericListSection data={data.bot_personas || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Channel Integrations" badge={`${data.channel_integrations?.length ?? 0}`}>
              <GenericListSection data={data.channel_integrations || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Channel Heartbeats" badge={`${data.channel_heartbeats?.length ?? 0}`}>
              <GenericListSection data={data.channel_heartbeats || []} />
            </CollapsibleSection>
          </View>
        ) : null}
      </RefreshableScrollView>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </View>
  );
}
