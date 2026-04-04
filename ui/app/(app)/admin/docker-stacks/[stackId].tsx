/**
 * Docker Stack detail page — stack info, services, logs, and actions.
 */
import { useState } from "react";
import { View, Text, Pressable, ActivityIndicator, ScrollView } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import {
  useDockerStack,
  useDockerStackStatus,
  useDockerStackLogs,
  useStartDockerStack,
  useStopDockerStack,
  useDestroyDockerStack,
} from "@/src/api/hooks/useDockerStacks";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Boxes, ArrowLeft, Play, Square, Trash2,
  CheckCircle2, XCircle, Loader2, AlertTriangle, Minus,
  Server, FileCode, ScrollText,
} from "lucide-react";
import { useLocalSearchParams, useRouter } from "expo-router";
import type { DockerStackServiceStatus } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Status badge (reusable)
// ---------------------------------------------------------------------------

function getStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "running":
      return { color: t.success, bg: t.successSubtle, border: t.successBorder, icon: CheckCircle2 };
    case "starting":
      return { color: t.accent, bg: t.accentSubtle, border: t.accentBorder, icon: Loader2 };
    case "stopped":
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: Minus };
    case "error":
      return { color: t.danger, bg: t.dangerSubtle, border: t.dangerBorder, icon: XCircle };
    case "removing":
      return { color: t.warning, bg: t.warningSubtle, border: t.warningBorder, icon: Loader2 };
    default:
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: AlertTriangle };
  }
}

function StatusBadge({ status, t }: { status: string; t: ThemeTokens }) {
  const style = getStatusStyle(status, t);
  const Icon = style.icon;
  return (
    <View
      className="flex-row items-center gap-1 rounded-full px-2.5 py-1"
      style={{ backgroundColor: style.bg, borderWidth: 1, borderColor: style.border }}
    >
      <Icon size={14} color={style.color} />
      <Text className="text-sm font-medium" style={{ color: style.color }}>
        {status}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

type Tab = "services" | "compose" | "logs";

function TabButton({
  label,
  icon: Icon,
  active,
  onPress,
  t,
}: {
  label: string;
  icon: React.ComponentType<{ size: number; color: string }>;
  active: boolean;
  onPress: () => void;
  t: ThemeTokens;
}) {
  return (
    <Pressable
      onPress={onPress}
      className={`flex-row items-center gap-1.5 px-3 py-2 rounded-lg ${
        active ? "bg-accent/15" : "hover:bg-surface-overlay"
      }`}
    >
      <Icon size={14} color={active ? t.accent : t.textDim} />
      <Text
        className="text-sm font-medium"
        style={{ color: active ? t.accent : t.textMuted }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Services Tab
// ---------------------------------------------------------------------------

function ServicesTab({
  services,
  isLoading,
  t,
}: {
  services: DockerStackServiceStatus[] | undefined;
  isLoading: boolean;
  t: ThemeTokens;
}) {
  if (isLoading) {
    return (
      <View className="items-center py-8">
        <ActivityIndicator size="small" color={t.accent} />
      </View>
    );
  }
  if (!services || services.length === 0) {
    return (
      <View className="items-center py-8">
        <Text className="text-sm" style={{ color: t.textDim }}>
          No services running
        </Text>
      </View>
    );
  }
  return (
    <View className="gap-2">
      {services.map((svc) => {
        const stStyle = getStatusStyle(svc.state, t);
        return (
          <View
            key={svc.name}
            className="rounded-lg p-3 flex-row items-center justify-between"
            style={{
              backgroundColor: t.surfaceRaised,
              borderWidth: 1,
              borderColor: t.surfaceBorder,
            }}
          >
            <View className="flex-row items-center gap-2">
              <Server size={14} color={t.accent} />
              <Text className="text-sm font-medium" style={{ color: t.text }}>
                {svc.name}
              </Text>
            </View>
            <View className="flex-row items-center gap-3">
              {svc.ports.length > 0 && (
                <Text className="text-xs" style={{ color: t.textDim }}>
                  {svc.ports.map((p) => `${p.host_port}:${p.container_port}`).join(", ")}
                </Text>
              )}
              {svc.health && (
                <Text className="text-xs" style={{ color: t.textDim }}>
                  {svc.health}
                </Text>
              )}
              <View
                className="rounded-full px-2 py-0.5"
                style={{ backgroundColor: stStyle.bg, borderWidth: 1, borderColor: stStyle.border }}
              >
                <Text className="text-xs font-medium" style={{ color: stStyle.color }}>
                  {svc.state}
                </Text>
              </View>
            </View>
          </View>
        );
      })}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Compose Tab
// ---------------------------------------------------------------------------

function ComposeTab({ definition, t }: { definition: string; t: ThemeTokens }) {
  return (
    <View
      className="rounded-lg p-4"
      style={{
        backgroundColor: t.surfaceRaised,
        borderWidth: 1,
        borderColor: t.surfaceBorder,
      }}
    >
      <ScrollView horizontal>
        <Text
          className="text-xs font-mono"
          style={{ color: t.text, whiteSpace: "pre" } as any}
          selectable
        >
          {definition}
        </Text>
      </ScrollView>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Logs Tab
// ---------------------------------------------------------------------------

function LogsTab({
  stackId,
  services,
  t,
}: {
  stackId: string;
  services: DockerStackServiceStatus[] | undefined;
  t: ThemeTokens;
}) {
  const [selectedService, setSelectedService] = useState<string | undefined>();
  const { data: logsData, isLoading } = useDockerStackLogs(stackId, selectedService);

  return (
    <View className="gap-3">
      {/* Service filter */}
      {services && services.length > 0 && (
        <View className="flex-row flex-wrap gap-1.5">
          <Pressable
            onPress={() => setSelectedService(undefined)}
            className={`rounded-full px-3 py-1 ${!selectedService ? "bg-accent/15" : ""}`}
            style={{
              borderWidth: 1,
              borderColor: !selectedService ? t.accentBorder : t.surfaceBorder,
            }}
          >
            <Text
              className="text-xs font-medium"
              style={{ color: !selectedService ? t.accent : t.textMuted }}
            >
              All
            </Text>
          </Pressable>
          {services.map((svc) => (
            <Pressable
              key={svc.name}
              onPress={() => setSelectedService(svc.name)}
              className={`rounded-full px-3 py-1 ${selectedService === svc.name ? "bg-accent/15" : ""}`}
              style={{
                borderWidth: 1,
                borderColor: selectedService === svc.name ? t.accentBorder : t.surfaceBorder,
              }}
            >
              <Text
                className="text-xs font-medium"
                style={{ color: selectedService === svc.name ? t.accent : t.textMuted }}
              >
                {svc.name}
              </Text>
            </Pressable>
          ))}
        </View>
      )}

      {/* Logs output */}
      <View
        className="rounded-lg p-3"
        style={{
          backgroundColor: t.surfaceRaised,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          maxHeight: 500,
        }}
      >
        {isLoading ? (
          <ActivityIndicator size="small" color={t.accent} />
        ) : (
          <ScrollView>
            <Text
              className="text-xs font-mono"
              style={{ color: t.text, whiteSpace: "pre-wrap" } as any}
              selectable
            >
              {logsData?.logs || "No logs available"}
            </Text>
          </ScrollView>
        )}
      </View>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function DockerStackDetailPage() {
  const t = useThemeTokens();
  const router = useRouter();
  const { stackId } = useLocalSearchParams<{ stackId: string }>();
  const { data: stack, isLoading } = useDockerStack(stackId);
  const { data: services } = useDockerStackStatus(
    stackId,
    stack?.status === "running" || stack?.status === "starting"
  );
  const { refreshing, onRefresh } = usePageRefresh([["docker-stacks", stackId ?? ""]]);
  const startMutation = useStartDockerStack();
  const stopMutation = useStopDockerStack();
  const destroyMutation = useDestroyDockerStack();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [activeTab, setActiveTab] = useState<Tab>("services");

  if (isLoading) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator size="large" color={t.accent} />
      </View>
    );
  }

  if (!stack) {
    return (
      <View className="flex-1 items-center justify-center gap-2">
        <Text className="text-base" style={{ color: t.textMuted }}>
          Stack not found
        </Text>
        <Pressable onPress={() => router.back()}>
          <Text className="text-sm" style={{ color: t.accent }}>
            Go back
          </Text>
        </Pressable>
      </View>
    );
  }

  return (
    <>
      <MobileHeader title={stack.name} />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, paddingBottom: 80, gap: 16 }}
      >
        {/* Back + Title */}
        <View className="flex-row items-center gap-3">
          <Pressable onPress={() => router.push("/admin/docker-stacks" as any)} className="p-1">
            <ArrowLeft size={20} color={t.textMuted} />
          </Pressable>
          <Boxes size={22} color={t.accent} />
          <Text className="text-xl font-bold flex-1" style={{ color: t.text }}>
            {stack.name}
          </Text>
          <StatusBadge status={stack.status} t={t} />
        </View>

        {/* Info bar */}
        <View
          className="rounded-lg p-4 gap-2"
          style={{
            backgroundColor: t.surfaceRaised,
            borderWidth: 1,
            borderColor: t.surfaceBorder,
          }}
        >
          <View className="flex-row flex-wrap gap-4">
            <InfoItem label="Bot" value={stack.created_by_bot} t={t} />
            <InfoItem label="Project" value={stack.project_name} t={t} />
            {stack.network_name && <InfoItem label="Network" value={stack.network_name} t={t} />}
            {stack.last_started_at && (
              <InfoItem
                label="Last Started"
                value={new Date(stack.last_started_at).toLocaleString()}
                t={t}
              />
            )}
          </View>
          {stack.error_message && (
            <View className="rounded p-2 mt-1" style={{ backgroundColor: t.dangerSubtle }}>
              <Text className="text-xs" style={{ color: t.danger }}>
                {stack.error_message}
              </Text>
            </View>
          )}
          {stack.description && (
            <Text className="text-sm" style={{ color: t.textMuted }}>
              {stack.description}
            </Text>
          )}
        </View>

        {/* Actions */}
        <View className="flex-row gap-2">
          {(stack.status === "stopped" || stack.status === "error") && (
            <ActionButton
              label="Start"
              icon={Play}
              color={t.success}
              onPress={() => startMutation.mutate(stack.id)}
              loading={startMutation.isPending}
              t={t}
            />
          )}
          {stack.status === "running" && (
            <ActionButton
              label="Stop"
              icon={Square}
              color={t.warning}
              onPress={() => stopMutation.mutate(stack.id)}
              loading={stopMutation.isPending}
              t={t}
            />
          )}
          {(stack.status === "stopped" || stack.status === "error") && (
            <ActionButton
              label="Destroy"
              icon={Trash2}
              color={t.danger}
              onPress={async () => {
                const ok = await confirm(
                  "This will permanently destroy the stack and all its data volumes. This cannot be undone.",
                  { title: "Destroy Stack?", confirmLabel: "Destroy", variant: "danger" },
                );
                if (ok) {
                  destroyMutation.mutate(stack.id, {
                    onSuccess: () => router.push("/admin/docker-stacks" as any),
                  });
                }
              }}
              loading={destroyMutation.isPending}
              t={t}
            />
          )}
        </View>

        {/* Tabs */}
        <View className="flex-row gap-1">
          <TabButton
            label="Services"
            icon={Server}
            active={activeTab === "services"}
            onPress={() => setActiveTab("services")}
            t={t}
          />
          <TabButton
            label="Compose"
            icon={FileCode}
            active={activeTab === "compose"}
            onPress={() => setActiveTab("compose")}
            t={t}
          />
          <TabButton
            label="Logs"
            icon={ScrollText}
            active={activeTab === "logs"}
            onPress={() => setActiveTab("logs")}
            t={t}
          />
        </View>

        {/* Tab content */}
        {activeTab === "services" && (
          <ServicesTab services={services} isLoading={false} t={t} />
        )}
        {activeTab === "compose" && (
          <ComposeTab definition={stack.compose_definition} t={t} />
        )}
        {activeTab === "logs" && (
          <LogsTab stackId={stack.id} services={services} t={t} />
        )}
      </RefreshableScrollView>
      <ConfirmDialogSlot />
    </>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function InfoItem({ label, value, t }: { label: string; value: string; t: ThemeTokens }) {
  return (
    <View>
      <Text className="text-xs" style={{ color: t.textDim }}>
        {label}
      </Text>
      <Text className="text-sm font-medium" style={{ color: t.text }}>
        {value}
      </Text>
    </View>
  );
}

function ActionButton({
  label,
  icon: Icon,
  color,
  onPress,
  loading,
  t,
}: {
  label: string;
  icon: React.ComponentType<{ size: number; color: string }>;
  color: string;
  onPress: () => void;
  loading?: boolean;
  t: ThemeTokens;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={loading}
      className="flex-row items-center gap-1.5 rounded-lg px-3 py-2 hover:opacity-80"
      style={{
        borderWidth: 1,
        borderColor: color,
        opacity: loading ? 0.6 : 1,
      }}
    >
      {loading ? (
        <ActivityIndicator size={14} color={color} />
      ) : (
        <Icon size={14} color={color} />
      )}
      <Text className="text-sm font-medium" style={{ color }}>
        {label}
      </Text>
    </Pressable>
  );
}
