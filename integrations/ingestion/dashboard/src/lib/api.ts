/**
 * API client for Ingestion Dashboard.
 *
 * All requests go directly to the ingestion integration's API endpoints
 * at /integrations/ingestion/... using the auth token from the auth bridge.
 */

import { getToken } from "./auth-bridge";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CursorInfo {
  key: string;
  value: string;
  updated_at: string;
}

export interface StoreStats {
  total_processed: number;
  total_quarantined: number;
  processed_24h: number;
  quarantined_24h: number;
  last_cursor: CursorInfo[];
}

export interface QuarantineItem {
  id: number;
  source: string;
  source_id: string;
  risk_level: string;
  flags: string[];
  reason: string | null;
  metadata: Record<string, unknown> | null;
  quarantined_at: string;
}

export interface QuarantineItemDetail extends QuarantineItem {
  raw_content: string;
}

export interface StoreOverview {
  name: string;
  stats: StoreStats | null;
  quarantine_preview: QuarantineItem[];
  classifier_error_count: number;
  error?: string;
}

export interface OverviewResponse {
  stores: StoreOverview[];
}

export interface QuarantineResponse {
  items: QuarantineItem[];
  store: string;
  error?: string;
}

export interface QuarantineItemDetailResponse {
  item: QuarantineItemDetail | null;
  store: string;
  error?: string;
}

export interface ReprocessResponse {
  released: number;
  error?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const BASE = "/integrations/ingestion";

export async function fetchOverview(): Promise<OverviewResponse> {
  return get(`${BASE}/overview`);
}

export async function fetchQuarantine(
  storeName: string,
  limit = 50,
  source?: string,
): Promise<QuarantineResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (source) params.set("source", source);
  return get(`${BASE}/stores/${storeName}/quarantine?${params}`);
}

export async function fetchQuarantineItem(
  storeName: string,
  itemId: number,
): Promise<QuarantineItemDetailResponse> {
  return get(`${BASE}/stores/${storeName}/quarantine/${itemId}`);
}

export async function reprocess(
  storeName: string,
  body: { quarantine_ids?: number[]; reason_pattern?: string; source?: string },
): Promise<ReprocessResponse> {
  return post(`${BASE}/stores/${storeName}/reprocess`, body);
}
