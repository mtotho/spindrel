/**
 * Docker Stacks list page — view all agent-managed Docker Compose stacks.
 */
import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useDockerStacks, useStartDockerStack, useStopDockerStack, useDestroyDockerStack } from "@/src/api/hooks/useDockerStacks";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Boxes, Search, Play, Square, Trash2,
  CheckCircle2, XCircle, Loader2, AlertTriangle, Minus,
} from "lucide-react";
import { useRouter } from "expo-router";
import type { DockerStack } from "@/src/types/api";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function getStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "running":
      return { color: t.success, bg: t.successSubtle, border: t.successBorder, icon: CheckCircle2, label: "running" };
    case "starting":
      return { color: t.accent, bg: t.accentSubtle, border: t.accentBorder, icon: Loader2, label: "starting" };
    case "stopped":
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: Minus, label: "stopped" };
    case "error":
      return { color: t.danger, bg: t.dangerSubtle, border: t.dangerBorder, icon: XCircle, label: "error" };
    case "removing":
      return { color: t.warning, bg: t.warningSubtle, border: t.warningBorder, icon: Loader2, label: "removing" };
    default:
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: AlertTriangle, label: status };
  }
}

function StatusBadge({ status, t }: { status: string; t: ThemeTokens }) {
  const style = getStatusStyle(status, t);
  const Icon = style.icon;
  return (
    <View
      className="flex-row items-center gap-1 rounded-full px-2 py-0.5"
      style={{ backgroundColor: style.bg, borderWidth: 1, borderColor: style.border }}
    >
      <Icon size={12} color={style.color} />
      <Text className="text-xs font-medium" style={{ color: style.color }}>
        {style.label}
      </Text>
    </View>
  );
}

// ---------------------------------------------------------------------------
// Stack Card
// ---------------------------------------------------------------------------

function StackCard({
  stack,
  t,
  onStart,
  onStop,
  onDestroy,
}: {
  stack: DockerStack;
  t: ThemeTokens;
  onStart: (id: string) => void;
  onStop: (id: string) => void;
  onDestroy: (id: string) => void;
}) {
  const router = useRouter();
  const serviceCount = Object.keys(stack.container_ids || {}).length;

  return (
    <Pressable
      onPress={() => router.push(`/admin/docker-stacks/${stack.id}` as any)}
      className="rounded-lg p-4 hover:bg-surface-overlay active:bg-surface-overlay"
      style={{
        backgroundColor: t.surfaceRaised,
        borderWidth: 1,
        borderColor: t.surfaceBorder,
      }}
    >
      <View className="flex-row items-start justify-between">
        <View className="flex-1 gap-1">
          <View className="flex-row items-center gap-2">
            <Boxes size={16} color={t.accent} />
            <Text className="text-base font-semibold" style={{ color: t.text }}>
              {stack.name}
            </Text>
          </View>
          {stack.description ? (
            <Text className="text-sm" style={{ color: t.textMuted }} numberOfLines={1}>
              {stack.description}
            </Text>
          ) : null}
          <View className="flex-row items-center gap-3 mt-1">
            <Text className="text-xs" style={{ color: t.textDim }}>
              Bot: {stack.created_by_bot}
            </Text>
            {serviceCount > 0 && (
              <Text className="text-xs" style={{ color: t.textDim }}>
                {serviceCount} service{serviceCount !== 1 ? "s" : ""}
              </Text>
            )}
            {stack.created_at && (
              <Text className="text-xs" style={{ color: t.textDim }}>
                {new Date(stack.created_at).toLocaleDateString()}
              </Text>
            )}
          </View>
        </View>
        <View className="items-end gap-2">
          <StatusBadge status={stack.status} t={t} />
          <View className="flex-row gap-1">
            {stack.status === "stopped" && (
              <Pressable
                onPress={(e) => {
                  e.stopPropagation();
                  onStart(stack.id);
                }}
                className="rounded p-1.5 hover:bg-surface-overlay"
                style={{ borderWidth: 1, borderColor: t.surfaceBorder }}
              >
                <Play size={14} color={t.success} />
              </Pressable>
            )}
            {stack.status === "running" && (
              <Pressable
                onPress={(e) => {
                  e.stopPropagation();
                  onStop(stack.id);
                }}
                className="rounded p-1.5 hover:bg-surface-overlay"
                style={{ borderWidth: 1, borderColor: t.surfaceBorder }}
              >
                <Square size={14} color={t.warning} />
              </Pressable>
            )}
            {stack.status === "stopped" && (
              <Pressable
                onPress={(e) => {
                  e.stopPropagation();
                  onDestroy(stack.id);
                }}
                className="rounded p-1.5 hover:bg-surface-overlay"
                style={{ borderWidth: 1, borderColor: t.surfaceBorder }}
              >
                <Trash2 size={14} color={t.danger} />
              </Pressable>
            )}
          </View>
        </View>
      </View>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function DockerStacksPage() {
  const t = useThemeTokens();
  const { data: stacks, isLoading } = useDockerStacks();
  const { refreshing, onRefresh } = usePageRefresh([["docker-stacks"]]);
  const [search, setSearch] = useState("");
  const startMutation = useStartDockerStack();
  const stopMutation = useStopDockerStack();
  const destroyMutation = useDestroyDockerStack();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  const filtered = useMemo(() => {
    if (!stacks) return [];
    if (!search) return stacks;
    const q = search.toLowerCase();
    return stacks.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.created_by_bot.toLowerCase().includes(q) ||
        s.status.toLowerCase().includes(q)
    );
  }, [stacks, search]);

  const running = filtered.filter((s) => s.status === "running");
  const stopped = filtered.filter((s) => s.status === "stopped");
  const other = filtered.filter((s) => !["running", "stopped"].includes(s.status));

  const handleStart = (id: string) => startMutation.mutate(id);
  const handleStop = (id: string) => stopMutation.mutate(id);
  const handleDestroy = async (id: string) => {
    const ok = await confirm(
      "This will permanently destroy the stack and all its data volumes. This cannot be undone.",
      { title: "Destroy Stack?", confirmLabel: "Destroy", variant: "danger" },
    );
    if (ok) destroyMutation.mutate(id);
  };

  return (
    <>
      <MobileHeader title="Docker Stacks" />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, paddingBottom: 80, gap: 16 }}
      >
        {/* Header */}
        <View className="flex-row items-center justify-between">
          <View className="flex-row items-center gap-2">
            <Boxes size={22} color={t.accent} />
            <Text className="text-xl font-bold" style={{ color: t.text }}>
              Docker Stacks
            </Text>
            {stacks && (
              <View
                className="rounded-full px-2 py-0.5"
                style={{ backgroundColor: t.accentSubtle }}
              >
                <Text className="text-xs font-medium" style={{ color: t.accent }}>
                  {stacks.length}
                </Text>
              </View>
            )}
          </View>
        </View>

        {/* Search */}
        <View
          className="flex-row items-center gap-2 rounded-lg px-3 py-2"
          style={{
            backgroundColor: t.surfaceRaised,
            borderWidth: 1,
            borderColor: t.surfaceBorder,
          }}
        >
          <Search size={16} color={t.textDim} />
          <input
            type="text"
            placeholder="Search stacks..."
            value={search}
            onChange={(e: any) => setSearch(e.target.value)}
            style={{
              flex: 1,
              background: "transparent",
              border: "none",
              outline: "none",
              color: t.text,
              fontSize: 14,
            }}
          />
        </View>

        {isLoading ? (
          <View className="items-center py-12">
            <ActivityIndicator size="large" color={t.accent} />
          </View>
        ) : filtered.length === 0 ? (
          <View className="items-center py-12 gap-2">
            <Boxes size={40} color={t.textDim} />
            <Text className="text-base" style={{ color: t.textMuted }}>
              {search ? "No stacks match your search" : "No Docker stacks yet"}
            </Text>
            <Text className="text-sm" style={{ color: t.textDim }}>
              Bots with docker_stacks.enabled can create stacks via the manage_docker_stack tool.
            </Text>
          </View>
        ) : (
          <>
            {running.length > 0 && (
              <Section title="Running" count={running.length} t={t}>
                {running.map((s) => (
                  <StackCard key={s.id} stack={s} t={t} onStart={handleStart} onStop={handleStop} onDestroy={handleDestroy} />
                ))}
              </Section>
            )}
            {other.length > 0 && (
              <Section title="Starting / Error / Removing" count={other.length} t={t}>
                {other.map((s) => (
                  <StackCard key={s.id} stack={s} t={t} onStart={handleStart} onStop={handleStop} onDestroy={handleDestroy} />
                ))}
              </Section>
            )}
            {stopped.length > 0 && (
              <Section title="Stopped" count={stopped.length} t={t}>
                {stopped.map((s) => (
                  <StackCard key={s.id} stack={s} t={t} onStart={handleStart} onStop={handleStop} onDestroy={handleDestroy} />
                ))}
              </Section>
            )}
          </>
        )}
      </RefreshableScrollView>
      <ConfirmDialogSlot />
    </>
  );
}

function Section({
  title,
  count,
  t,
  children,
}: {
  title: string;
  count: number;
  t: ThemeTokens;
  children: React.ReactNode;
}) {
  return (
    <View className="gap-2">
      <View className="flex-row items-center gap-2">
        <Text className="text-sm font-semibold" style={{ color: t.textMuted }}>
          {title}
        </Text>
        <Text className="text-xs" style={{ color: t.textDim }}>
          ({count})
        </Text>
      </View>
      {children}
    </View>
  );
}
