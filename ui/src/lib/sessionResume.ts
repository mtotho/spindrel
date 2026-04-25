export const SESSION_RESUME_IDLE_MS = 2 * 60 * 60 * 1000;

export type SessionResumeSurfaceKind = "primary" | "channel" | "scratch" | "thread" | "session";

export interface SessionResumeMessageLike {
  role?: string | null;
  created_at?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface SessionResumeMetadata {
  sessionId: string;
  channelId?: string | null;
  surfaceKind: SessionResumeSurfaceKind;
  title?: string | null;
  summary?: string | null;
  createdAt?: string | null;
  lastActiveAt?: string | null;
  lastVisibleMessageAt?: string | null;
  messageCount?: number | null;
  sectionCount?: number | null;
  botName?: string | null;
  botModel?: string | null;
}

export interface SessionResumeDecisionInput {
  metadata: SessionResumeMetadata | null | undefined;
  enabled: boolean;
  dismissed: boolean;
  isActive: boolean;
  nowMs: number;
  idleMs?: number;
}

export function getNewestVisibleMessageAt(messages: readonly SessionResumeMessageLike[]): string | null {
  let newestMs = Number.NEGATIVE_INFINITY;
  let newest: string | null = null;
  for (const message of messages) {
    if (message.role !== "user" && message.role !== "assistant") continue;
    const metadata = message.metadata ?? {};
    if (
      metadata.kind === "task_run" ||
      metadata.kind === "thread_parent_preview" ||
      metadata.kind === "slash_command_result"
    ) continue;
    if (metadata.synthetic === true || metadata.ui_only === true) continue;
    const createdAt = message.created_at;
    if (!createdAt) continue;
    const ms = Date.parse(createdAt);
    if (!Number.isFinite(ms)) continue;
    if (ms > newestMs) {
      newestMs = ms;
      newest = createdAt;
    }
  }
  return newest;
}

export function sessionResumeDismissKey(
  sessionId: string | null | undefined,
  lastVisibleMessageAt: string | null | undefined,
): string | null {
  if (!sessionId || !lastVisibleMessageAt) return null;
  return `${sessionId}:${lastVisibleMessageAt}`;
}

export function shouldShowSessionResumeCard({
  metadata,
  enabled,
  dismissed,
  isActive,
  nowMs,
  idleMs = SESSION_RESUME_IDLE_MS,
}: SessionResumeDecisionInput): boolean {
  if (!enabled || dismissed || isActive || !metadata) return false;
  if (!metadata.sessionId || !metadata.lastVisibleMessageAt) return false;
  if ((metadata.messageCount ?? 1) <= 0) return false;
  const lastMs = Date.parse(metadata.lastVisibleMessageAt);
  if (!Number.isFinite(lastMs)) return false;
  return nowMs - lastMs >= idleMs;
}

export function formatSessionSurfaceLabel(kind: SessionResumeSurfaceKind): string {
  switch (kind) {
    case "primary":
      return "Primary session";
    case "scratch":
      return "Scratch session";
    case "thread":
      return "Thread session";
    case "channel":
      return "Previous chat";
    default:
      return "Session";
  }
}

export function compactSessionId(sessionId: string): string {
  if (sessionId.length <= 13) return sessionId;
  return `${sessionId.slice(0, 8)}...${sessionId.slice(-4)}`;
}
