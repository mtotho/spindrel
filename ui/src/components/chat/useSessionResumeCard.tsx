import { useEffect, useMemo, useState } from "react";
import type { Message } from "@/src/types/api";
import {
  useChannelSessionCatalog,
  useSessionSummary,
  type SessionSummaryResponse,
} from "@/src/api/hooks/useChannelSessions";
import { useSessionHarnessStatus } from "@/src/api/hooks/useApprovals";
import { useBot } from "@/src/api/hooks/useBots";
import {
  getNewestVisibleMessageAt,
  shouldShowSessionResumeCard,
  type SessionResumeMetadata,
  type SessionResumeSurfaceKind,
} from "@/src/lib/sessionResume";
import { useSessionResumePrefs } from "@/src/stores/sessionResumePref";
import { SessionResumeCard } from "./SessionResumeCard";

interface UseSessionResumeCardArgs {
  sessionId?: string | null;
  channelId?: string | null;
  messages: readonly Message[];
  isActive?: boolean;
  chatMode?: "default" | "terminal";
  seed?: Partial<SessionResumeMetadata>;
  onOpenSessions?: () => void;
}

function surfaceKindFromSummary(
  summary: SessionSummaryResponse | undefined,
  fallback: SessionResumeSurfaceKind,
): SessionResumeSurfaceKind {
  if (!summary) return fallback;
  if (summary.session_scope === "primary") return "primary";
  if (summary.session_scope === "scratch" || summary.session_type === "ephemeral") return "scratch";
  if (summary.parent_channel_id && summary.session_type === "thread") return "thread";
  if (summary.channel_id) return "channel";
  return fallback;
}

export function useSessionResumeCard({
  sessionId,
  channelId,
  messages,
  isActive = false,
  chatMode = "default",
  seed,
  onOpenSessions,
}: UseSessionResumeCardArgs) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  const lastVisibleMessageAt = useMemo(
    () => getNewestVisibleMessageAt(messages),
    [messages],
  );
  const prefs = useSessionResumePrefs(channelId, sessionId, lastVisibleMessageAt);
  const { data: catalog } = useChannelSessionCatalog(channelId);
  const catalogRow = useMemo(
    () => catalog?.find((row) => row.session_id === sessionId),
    [catalog, sessionId],
  );
  const { data: summary } = useSessionSummary(sessionId, !catalogRow);
  const { data: bot } = useBot(catalogRow?.bot_id ?? summary?.bot_id ?? undefined);
  const isHarnessBot = !!bot?.harness_runtime;
  const { data: harnessStatus } = useSessionHarnessStatus(sessionId, isHarnessBot);

  const metadata = useMemo<SessionResumeMetadata | null>(() => {
    if (!sessionId || !lastVisibleMessageAt) return null;
    const fallbackKind = seed?.surfaceKind ?? "session";
    const seededBotModel = isHarnessBot ? null : seed?.botModel;
    const resolvedBotModel = isHarnessBot
      ? (harnessStatus?.model ?? null)
      : (bot?.model ?? null);
    return {
      sessionId,
      channelId: channelId ?? seed?.channelId ?? summary?.channel_id ?? summary?.parent_channel_id ?? null,
      surfaceKind: catalogRow
        ? catalogRow.is_active
          ? "primary"
          : catalogRow.surface_kind
        : surfaceKindFromSummary(summary, fallbackKind),
      title: seed?.title ?? catalogRow?.label ?? summary?.title ?? null,
      summary: seed?.summary ?? catalogRow?.summary ?? summary?.summary ?? null,
      createdAt: seed?.createdAt ?? catalogRow?.created_at ?? summary?.created_at ?? null,
      lastActiveAt: seed?.lastActiveAt ?? catalogRow?.last_active ?? summary?.last_active ?? null,
      lastVisibleMessageAt,
      messageCount: seed?.messageCount ?? catalogRow?.message_count ?? summary?.message_count ?? messages.length,
      sectionCount: seed?.sectionCount ?? catalogRow?.section_count ?? summary?.section_count ?? 0,
      botName: seed?.botName ?? bot?.name ?? null,
      botModel: seededBotModel ?? resolvedBotModel,
    };
  }, [
    bot?.harness_runtime,
    bot?.model,
    bot?.name,
    catalogRow,
    channelId,
    harnessStatus?.model,
    isHarnessBot,
    lastVisibleMessageAt,
    messages.length,
    seed,
    sessionId,
    summary,
  ]);

  const show = shouldShowSessionResumeCard({
    metadata,
    enabled: prefs.enabled,
    dismissed: prefs.dismissed,
    isActive,
    nowMs,
  });

  if (!show || !metadata) return null;

  return (
    <SessionResumeCard
      metadata={metadata}
      chatMode={chatMode}
      onDismiss={prefs.dismissCurrent}
      onHideChannel={channelId ? prefs.hideChannel : undefined}
      onHideGlobal={prefs.hideGlobal}
      onOpenSessions={onOpenSessions}
    />
  );
}
