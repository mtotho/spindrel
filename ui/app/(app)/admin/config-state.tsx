import { useState, useCallback } from "react";
import { View, Text, ScrollView, ActivityIndicator, Pressable } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { Copy, Check, ChevronDown, ChevronRight } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { MobileHeader } from "@/src/components/layout/MobileHeader";

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
  const [open, setOpen] = useState(defaultOpen);
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <View style={{ marginBottom: 2 }}>
      <Pressable
        onPress={() => setOpen((p) => !p)}
        className="flex-row items-center gap-2 rounded-md px-3 py-2.5 hover:bg-surface-overlay active:bg-surface-overlay"
      >
        <Icon size={14} color="#888" />
        <Text style={{ fontSize: 13, fontWeight: "600", color: "#e5e5e5" }}>
          {title}
        </Text>
        {badge ? (
          <Text style={{ fontSize: 11, color: "#666", marginLeft: 4 }}>
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
          color: "#888",
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
          color: "#ccc",
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
  const [expanded, setExpanded] = useState(false);
  if (!expanded) {
    return (
      <Pressable onPress={() => setExpanded(true)}>
        <Text style={{ fontSize: 11, color: "#555", fontFamily: "monospace" }}>
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
  return (
    <>
      {data.map((p) => (
        <View key={p.id} style={{ marginBottom: 4 }}>
          <View className="flex-row items-center gap-2" style={{ paddingVertical: 2 }}>
            <Text style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace", fontWeight: "600" }}>
              {p.display_name}
            </Text>
            <Text style={{ fontSize: 11, color: "#666", fontFamily: "monospace" }}>
              {p.provider_type}
            </Text>
            <Text style={{ fontSize: 11, color: p.is_enabled ? "#22c55e" : "#ef4444", fontFamily: "monospace" }}>
              {p.is_enabled ? "enabled" : "disabled"}
            </Text>
            <Text style={{ fontSize: 11, color: "#666", fontFamily: "monospace" }}>
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
  return (
    <>
      {data.map((b) => (
        <View key={b.id} style={{ marginBottom: 6 }}>
          <View className="flex-row items-center gap-2 flex-wrap" style={{ paddingVertical: 2 }}>
            <Text style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace", fontWeight: "600" }}>
              {b.name}
            </Text>
            <Text style={{ fontSize: 11, color: "#888", fontFamily: "monospace" }}>
              {b.model}
            </Text>
          </View>
          <View className="flex-row flex-wrap gap-x-3" style={{ paddingVertical: 1 }}>
            <Tag label="tools" value={b.local_tools?.length ?? 0} />
            <Tag label="mcp" value={b.mcp_servers?.length ?? 0} />
            <Tag label="skills" value={b.skills?.length ?? 0} />
            <Tag label="memory" value={b.memory?.enabled ? "on" : "off"} on={b.memory?.enabled} />
            <Tag label="knowledge" value={b.knowledge?.enabled ? "on" : "off"} on={b.knowledge?.enabled} />
            <Tag label="compaction" value={b.context_compaction ? "on" : "off"} on={b.context_compaction} />
            {b.elevation_enabled && <Tag label="elevation" value="on" on />}
          </View>
          <DetailJSON data={b} />
        </View>
      ))}
    </>
  );
}

function Tag({ label, value, on }: { label: string; value: any; on?: boolean }) {
  return (
    <Text style={{ fontSize: 11, color: on ? "#3b82f6" : "#666", fontFamily: "monospace" }}>
      {label}:{String(value)}
    </Text>
  );
}

function ChannelsSection({ data }: { data: any[] }) {
  return (
    <>
      {data.map((ch) => (
        <View key={ch.id} style={{ marginBottom: 4 }}>
          <View className="flex-row items-center gap-2" style={{ paddingVertical: 2 }}>
            <Text style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace", fontWeight: "600" }}>
              {ch.name}
            </Text>
            <Text style={{ fontSize: 11, color: "#888", fontFamily: "monospace" }}>
              bot:{ch.bot_id}
            </Text>
            {ch.integration && (
              <Text style={{ fontSize: 11, color: "#666", fontFamily: "monospace" }}>
                {ch.integration}
              </Text>
            )}
            {Object.keys(ch.overrides || {}).length > 0 && (
              <Text style={{ fontSize: 11, color: "#3b82f6", fontFamily: "monospace" }}>
                {Object.keys(ch.overrides).length} overrides
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
  return (
    <>
      {data.map((ws) => (
        <View key={ws.id} style={{ marginBottom: 4 }}>
          <View className="flex-row items-center gap-2" style={{ paddingVertical: 2 }}>
            <Text style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace", fontWeight: "600" }}>
              {ws.name}
            </Text>
            <Text style={{ fontSize: 11, color: "#888", fontFamily: "monospace" }}>
              {ws.image}
            </Text>
            <Text
              style={{
                fontSize: 11,
                color: ws.status === "running" ? "#22c55e" : "#666",
                fontFamily: "monospace",
              }}
            >
              {ws.status}
            </Text>
            <Text style={{ fontSize: 11, color: "#666", fontFamily: "monospace" }}>
              {ws.bots?.length ?? 0} bots
            </Text>
          </View>
        </View>
      ))}
    </>
  );
}

function SkillsSection({ data }: { data: any[] }) {
  return (
    <>
      {data.map((s) => (
        <View key={s.id} className="flex-row items-center gap-3" style={{ paddingVertical: 2 }}>
          <Text style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace", fontWeight: "600", minWidth: 160 }}>
            {s.name}
          </Text>
          <Text style={{ fontSize: 11, color: "#888", fontFamily: "monospace" }}>
            {s.source_type}
          </Text>
          <Text style={{ fontSize: 11, color: "#666", fontFamily: "monospace" }}>
            {s.chunk_count} chunks
          </Text>
        </View>
      ))}
    </>
  );
}

function TasksSection({ data }: { data: any[] }) {
  if (data.length === 0) {
    return <Text style={{ fontSize: 12, color: "#555", fontFamily: "monospace" }}>No active or recurring tasks</Text>;
  }
  return (
    <>
      {data.map((t) => (
        <View key={t.id} className="flex-row items-center gap-3" style={{ paddingVertical: 2 }}>
          <Text style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace", fontWeight: "600" }}>
            {t.title || t.bot_id}
          </Text>
          <Text style={{ fontSize: 11, color: "#888", fontFamily: "monospace" }}>
            {t.task_type}
          </Text>
          {t.recurrence && (
            <Text style={{ fontSize: 11, color: "#3b82f6", fontFamily: "monospace" }}>
              every {t.recurrence}
            </Text>
          )}
          <Text
            style={{
              fontSize: 11,
              color: t.status === "running" ? "#22c55e" : t.status === "pending" ? "#eab308" : "#666",
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
  return (
    <>
      {data.map((u) => (
        <View key={u.id} className="flex-row items-center gap-3" style={{ paddingVertical: 2 }}>
          <Text style={{ fontSize: 12, color: "#e5e5e5", fontFamily: "monospace", fontWeight: "600" }}>
            {u.display_name}
          </Text>
          <Text style={{ fontSize: 11, color: "#888", fontFamily: "monospace" }}>
            {u.email}
          </Text>
          <Text style={{ fontSize: 11, color: u.is_admin ? "#3b82f6" : "#666", fontFamily: "monospace" }}>
            {u.is_admin ? "admin" : "user"}
          </Text>
          {!u.is_active && (
            <Text style={{ fontSize: 11, color: "#ef4444", fontFamily: "monospace" }}>
              inactive
            </Text>
          )}
        </View>
      ))}
    </>
  );
}

export default function ConfigStatePage() {
  const { data, isLoading, error } = useConfigState();
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback: noop
    }
  }, [data]);

  const CopyButton = (
    <Pressable
      onPress={handleCopy}
      disabled={!data}
      className="flex-row items-center gap-1.5 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay"
      style={{ opacity: data ? 1 : 0.4 }}
    >
      {copied ? <Check size={14} color="#22c55e" /> : <Copy size={14} color="#888" />}
      <Text style={{ fontSize: 12, color: copied ? "#22c55e" : "#888" }}>
        {copied ? "Copied" : "Copy JSON"}
      </Text>
    </Pressable>
  );

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      <MobileHeader title="Config State" right={CopyButton} />
      <ScrollView
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, maxWidth: 960 }}
      >
        {isLoading ? (
          <View style={{ padding: 40, alignItems: "center" }}>
            <ActivityIndicator color="#3b82f6" />
          </View>
        ) : error ? (
          <Text style={{ color: "#ef4444", fontSize: 13 }}>
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
                <Text style={{ fontSize: 12, color: "#555", fontFamily: "monospace" }}>
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
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}
