/**
 * API client for Mission Control.
 *
 * All requests go directly to the MC integration's own API endpoints
 * at /integrations/mission_control/... using the auth token from the
 * auth bridge (received via postMessage or localStorage).
 */

import { getToken } from "./auth-bridge";
import type {
  DailyLog,
  FileChannel,
  OverviewData,
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

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PUT",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PUT ${path}: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// MC integration API (direct — same origin)
// ---------------------------------------------------------------------------

const MC = "/integrations/mission_control";

export async function fetchOverview(): Promise<OverviewData> {
  return get(`${MC}/overview`);
}

// ---------------------------------------------------------------------------
// Workspace file access (via MC integration endpoints)
// ---------------------------------------------------------------------------

export async function fetchFileChannels(): Promise<FileChannel[]> {
  // The overview endpoint includes channels with workspace info
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
  // Daily logs are workspace files in the memory/daily/ directory
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
