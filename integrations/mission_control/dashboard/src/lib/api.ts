/**
 * API client for Mission Control.
 *
 * All requests go directly to the MC integration's own API endpoints
 * at /integrations/mission_control/... using the auth token from the
 * auth bridge (received via postMessage or localStorage).
 */

import { getToken } from "./auth-bridge";
import type {
  AggregatedKanbanColumn,
  ChannelContext,
  DailyLog,
  FileChannel,
  JournalEntry,
  MCPrefs,
  MemorySection,
  OverviewData,
  Plan,
  ReadinessData,
  TimelineEvent,
  WorkspaceFile,
} from "./types";

function headers(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: headers() });
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: headers(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path}: ${res.status}`);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PUT ${path}: ${res.status}`);
  return res.json();
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${path}: ${res.status}`);
  return res.json();
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(path, { method: "DELETE", headers: headers() });
  if (!res.ok) throw new Error(`DELETE ${path}: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// MC integration API (direct — same origin)
// ---------------------------------------------------------------------------

const MC = "/integrations/mission_control";

// Overview
export async function fetchOverview(scope?: string): Promise<OverviewData> {
  const qs = scope ? `?scope=${scope}` : "";
  return get(`${MC}/overview${qs}`);
}

// ---------------------------------------------------------------------------
// Kanban (aggregated)
// ---------------------------------------------------------------------------

export async function fetchKanban(scope?: string): Promise<AggregatedKanbanColumn[]> {
  const qs = scope ? `?scope=${scope}` : "";
  const data = await get<{ columns: AggregatedKanbanColumn[] }>(`${MC}/kanban${qs}`);
  return data.columns;
}

export async function kanbanMove(body: {
  card_id: string;
  from_column: string;
  to_column: string;
  channel_id: string;
}): Promise<void> {
  await post(`${MC}/kanban/move`, body);
}

export async function kanbanCreate(body: {
  channel_id: string;
  title: string;
  column?: string;
  priority?: string;
  assigned?: string;
  tags?: string;
  due?: string;
  description?: string;
}): Promise<void> {
  await post(`${MC}/kanban/create`, body);
}

export async function kanbanUpdate(body: {
  channel_id: string;
  card_id: string;
  title?: string;
  description?: string;
  priority?: string;
  assigned?: string;
  due?: string;
  tags?: string;
}): Promise<void> {
  await patch(`${MC}/kanban/update`, body);
}

// ---------------------------------------------------------------------------
// Journal
// ---------------------------------------------------------------------------

export async function fetchJournal(
  days = 7,
  scope?: string,
): Promise<JournalEntry[]> {
  const params = new URLSearchParams({ days: String(days) });
  if (scope) params.set("scope", scope);
  const data = await get<{ entries: JournalEntry[] }>(`${MC}/journal?${params}`);
  return data.entries;
}

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

export async function fetchTimeline(
  days = 7,
  scope?: string,
): Promise<TimelineEvent[]> {
  const params = new URLSearchParams({ days: String(days) });
  if (scope) params.set("scope", scope);
  const data = await get<{ events: TimelineEvent[] }>(`${MC}/timeline?${params}`);
  return data.events;
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export async function fetchMemory(scope?: string): Promise<MemorySection[]> {
  const qs = scope ? `?scope=${scope}` : "";
  const data = await get<{ sections: MemorySection[] }>(`${MC}/memory${qs}`);
  return data.sections;
}

export async function fetchReferenceFile(
  botId: string,
  filename: string,
): Promise<string> {
  const data = await get<{ content: string }>(
    `${MC}/memory/${botId}/reference/${encodeURIComponent(filename)}`,
  );
  return data.content;
}

export interface MemorySearchResult {
  file_path: string;
  content: string;
  score: number;
  bot_id: string;
  bot_name: string;
}

export async function searchMemory(
  query: string,
  scope?: string,
  topK = 10,
): Promise<MemorySearchResult[]> {
  const params = new URLSearchParams();
  if (scope) params.set("scope", scope);
  const qs = params.toString();
  const data = await post<{ results: MemorySearchResult[] }>(
    `${MC}/memory/search${qs ? `?${qs}` : ""}`,
    { query, top_k: topK },
  );
  return data.results;
}

// ---------------------------------------------------------------------------
// Plans
// ---------------------------------------------------------------------------

export async function fetchPlans(
  scope?: string,
  status?: string,
): Promise<Plan[]> {
  const params = new URLSearchParams();
  if (scope) params.set("scope", scope);
  if (status) params.set("status", status);
  const qs = params.toString();
  const data = await get<{ plans: Plan[] }>(`${MC}/plans${qs ? `?${qs}` : ""}`);
  return data.plans;
}

export async function fetchPlan(
  channelId: string,
  planId: string,
): Promise<Plan> {
  return get(`${MC}/channels/${channelId}/plans/${planId}`);
}

export async function createPlan(
  channelId: string,
  body: {
    title: string;
    notes?: string;
    steps: Array<{ content: string; requires_approval?: boolean }>;
  },
): Promise<{ ok: boolean; plan_id: string; status: string }> {
  return post(`${MC}/channels/${channelId}/plans`, body);
}

export async function updatePlan(
  channelId: string,
  planId: string,
  body: {
    title?: string;
    notes?: string;
    steps?: Array<{ content: string; requires_approval?: boolean }>;
  },
): Promise<void> {
  await patch(`${MC}/channels/${channelId}/plans/${planId}`, body);
}

export async function deletePlan(
  channelId: string,
  planId: string,
): Promise<void> {
  await del(`${MC}/channels/${channelId}/plans/${planId}`);
}

export async function approvePlan(
  channelId: string,
  planId: string,
): Promise<void> {
  await post(`${MC}/channels/${channelId}/plans/${planId}/approve`);
}

export async function rejectPlan(
  channelId: string,
  planId: string,
): Promise<void> {
  await post(`${MC}/channels/${channelId}/plans/${planId}/reject`);
}

export async function resumePlan(
  channelId: string,
  planId: string,
): Promise<void> {
  await post(`${MC}/channels/${channelId}/plans/${planId}/resume`);
}

export async function approveStep(
  channelId: string,
  planId: string,
  position: number,
): Promise<void> {
  await post(
    `${MC}/channels/${channelId}/plans/${planId}/steps/${position}/approve`,
  );
}

export async function skipStep(
  channelId: string,
  planId: string,
  position: number,
): Promise<void> {
  await post(
    `${MC}/channels/${channelId}/plans/${planId}/steps/${position}/skip`,
  );
}

// ---------------------------------------------------------------------------
// Preferences
// ---------------------------------------------------------------------------

export async function fetchPrefs(): Promise<MCPrefs> {
  return get(`${MC}/prefs`);
}

export async function updatePrefs(body: Partial<MCPrefs>): Promise<MCPrefs> {
  return put(`${MC}/prefs`, body);
}

// ---------------------------------------------------------------------------
// Readiness
// ---------------------------------------------------------------------------

export async function fetchReadiness(): Promise<ReadinessData> {
  return get(`${MC}/readiness`);
}

export async function fetchSetupGuide(): Promise<string> {
  const data = await get<{ content: string }>(`${MC}/setup-guide`);
  return data.content;
}

// ---------------------------------------------------------------------------
// Channel context (debug)
// ---------------------------------------------------------------------------

export async function fetchChannelContext(
  channelId: string,
): Promise<ChannelContext> {
  return get(`${MC}/channels/${channelId}/context`);
}

// ---------------------------------------------------------------------------
// Channel membership
// ---------------------------------------------------------------------------

export async function joinChannel(channelId: string): Promise<void> {
  await post(`${MC}/channels/${channelId}/join`);
}

export async function leaveChannel(channelId: string): Promise<void> {
  await del(`${MC}/channels/${channelId}/join`);
}

// ---------------------------------------------------------------------------
// Workspace file access (via MC integration endpoints)
// ---------------------------------------------------------------------------

export async function fetchFileChannels(): Promise<FileChannel[]> {
  const overview = await fetchOverview();
  return (overview.channels || [])
    .filter((ch) => ch.workspace_enabled)
    .map((ch) => ({
      id: ch.id,
      display_name: ch.name || undefined,
      name: ch.name,
      bot_id: ch.bot_id,
      workspace_enabled: ch.workspace_enabled,
    }));
}

export async function fetchChannelFiles(
  channelId: string,
  includeArchive = false,
): Promise<WorkspaceFile[]> {
  const qs = includeArchive ? "?include_archive=true" : "";
  const data = await get<{ files: WorkspaceFile[] }>(
    `${MC}/channels/${channelId}/workspace/files${qs}`,
  );
  return data.files;
}

export async function fetchFileContent(
  channelId: string,
  filePath: string,
): Promise<string> {
  const data = await get<{ content: string }>(
    `${MC}/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(filePath)}`,
  );
  return data.content;
}

export async function writeFileContent(
  channelId: string,
  filePath: string,
  content: string,
): Promise<void> {
  await put(
    `${MC}/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(filePath)}`,
    { content },
  );
}

export async function fetchDailyLogs(
  channelId: string,
  limit = 7,
): Promise<DailyLog[]> {
  const files = await fetchChannelFiles(channelId);
  const logFiles = files
    .filter((f) => f.path.startsWith("memory/daily/") && f.path.endsWith(".md"))
    .sort((a, b) => b.path.localeCompare(a.path))
    .slice(0, limit);

  const logs: DailyLog[] = [];
  for (const f of logFiles) {
    const content = await fetchFileContent(channelId, f.path);
    const dateMatch = f.path.match(/(\d{4}-\d{2}-\d{2})/);
    logs.push({
      date: dateMatch ? dateMatch[1] : f.path,
      content,
    });
  }
  return logs;
}
