/**
 * API client for Mission Control.
 *
 * Two data paths:
 * 1. /api/files/*  — reads from the mounted workspace volume (Express backend)
 * 2. /api/proxy/*  — forwards to the agent server API (authenticated)
 */

import type {
  DailyLog,
  FileChannel,
  OverviewData,
  WorkspaceFile,
} from "./types";

const BASE = "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);
  return res.json();
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PUT ${path}: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Agent server (proxied)
// ---------------------------------------------------------------------------

export async function fetchOverview(): Promise<OverviewData> {
  return get("/api/proxy/integrations/mission-control/overview");
}

// ---------------------------------------------------------------------------
// File system (direct from Express backend)
// ---------------------------------------------------------------------------

export async function fetchFileChannels(): Promise<FileChannel[]> {
  const data = await get<{ channels: FileChannel[] }>("/api/files/channels");
  return data.channels;
}

export async function fetchChannelFiles(
  channelId: string,
  includeArchive = false,
): Promise<WorkspaceFile[]> {
  const qs = includeArchive ? "?include_archive=true" : "";
  const data = await get<{ files: WorkspaceFile[] }>(
    `/api/files/channels/${channelId}/files${qs}`,
  );
  return data.files;
}

export async function fetchFileContent(
  channelId: string,
  filePath: string,
): Promise<string> {
  const data = await get<{ content: string }>(
    `/api/files/channels/${channelId}/content?path=${encodeURIComponent(filePath)}`,
  );
  return data.content;
}

export async function writeFileContent(
  channelId: string,
  filePath: string,
  content: string,
): Promise<void> {
  await put(
    `/api/proxy/integrations/mission-control/channels/${channelId}/workspace/files/content?path=${encodeURIComponent(filePath)}`,
    { content },
  );
}

export async function fetchDailyLogs(
  channelId: string,
  limit = 7,
): Promise<DailyLog[]> {
  const data = await get<{ logs: DailyLog[] }>(
    `/api/files/channels/${channelId}/logs?limit=${limit}`,
  );
  return data.logs;
}
