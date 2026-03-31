import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MCChannelOverview {
  id: string;
  name: string;
  bot_id: string;
  bot_name: string | null;
  model: string | null;
  workspace_enabled: boolean;
  task_count: number;
  template_name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MCBotOverview {
  id: string;
  name: string;
  model: string;
  channel_count: number;
  memory_scheme: string | null;
}

export interface MCOverview {
  channels: MCChannelOverview[];
  bots: MCBotOverview[];
  total_channels: number;
  total_bots: number;
  total_tasks: number;
}

export interface MCKanbanCard {
  title: string;
  meta: Record<string, string>;
  description: string;
  channel_id: string;
  channel_name: string;
}

export interface MCKanbanColumn {
  name: string;
  cards: MCKanbanCard[];
}

export interface MCKanbanResponse {
  columns: MCKanbanColumn[];
}

export interface MCJournalEntry {
  date: string;
  bot_id: string;
  bot_name: string;
  content: string;
}

export interface MCMemorySection {
  bot_id: string;
  bot_name: string;
  memory_content: string | null;
  reference_files: string[];
}

export interface MCChannelContext {
  config: {
    channel_id: string;
    channel_name: string;
    bot_id: string;
    bot_name: string;
    model: string;
    workspace_enabled: boolean;
    workspace_rag: boolean;
    context_compaction: boolean;
    memory_scheme: string | null;
    history_mode: string | null;
    tools: string[];
    mcp_servers: string[];
    skills: string[];
    pinned_tools: string[];
  };
  schema: {
    template_name: string | null;
    content: string | null;
  };
  files: Array<{
    name: string;
    path: string;
    size: number;
    modified_at: number;
    section: string;
  }>;
  tool_calls: Array<{
    id: string;
    tool_name: string;
    tool_type: string;
    arguments: Record<string, unknown>;
    result: string;
    error: string | null;
    duration_ms: number | null;
    created_at: string | null;
  }>;
  trace_events: Array<{
    id: string;
    event_type: string;
    event_name: string | null;
    data: Record<string, unknown> | null;
    duration_ms: number | null;
    created_at: string | null;
  }>;
}

export interface MCPrefs {
  tracked_channel_ids: string[] | null;
  tracked_bot_ids: string[] | null;
  kanban_filters: Record<string, unknown>;
  layout_prefs: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useMCOverview() {
  return useQuery({
    queryKey: ["mc-overview"],
    queryFn: () => apiFetch<MCOverview>("/api/v1/mission-control/overview"),
  });
}

export function useMCKanban() {
  return useQuery({
    queryKey: ["mc-kanban"],
    queryFn: () => apiFetch<MCKanbanResponse>("/api/v1/mission-control/kanban"),
  });
}

export function useMCKanbanMove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      card_id: string;
      from_column: string;
      to_column: string;
      channel_id: string;
    }) =>
      apiFetch("/api/v1/mission-control/kanban/move", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-kanban"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
    },
  });
}

export function useMCKanbanCreate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      channel_id: string;
      title: string;
      column?: string;
      priority?: string;
      assigned?: string;
      tags?: string;
      due?: string;
      description?: string;
    }) =>
      apiFetch("/api/v1/mission-control/kanban/create", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-kanban"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
    },
  });
}

export function useMCJournal(days = 7) {
  return useQuery({
    queryKey: ["mc-journal", days],
    queryFn: () =>
      apiFetch<{ entries: MCJournalEntry[] }>(
        `/api/v1/mission-control/journal?days=${days}`
      ),
  });
}

export function useMCMemory() {
  return useQuery({
    queryKey: ["mc-memory"],
    queryFn: () =>
      apiFetch<{ sections: MCMemorySection[] }>(
        "/api/v1/mission-control/memory"
      ),
  });
}

export function useMCChannelContext(channelId: string | undefined) {
  return useQuery({
    queryKey: ["mc-channel-context", channelId],
    queryFn: () =>
      apiFetch<MCChannelContext>(
        `/api/v1/mission-control/channels/${channelId}/context`
      ),
    enabled: !!channelId,
  });
}

export function useMCPrefs() {
  return useQuery({
    queryKey: ["mc-prefs"],
    queryFn: () => apiFetch<MCPrefs>("/api/v1/mission-control/prefs"),
  });
}

export function useUpdateMCPrefs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<MCPrefs>) =>
      apiFetch<MCPrefs>("/api/v1/mission-control/prefs", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-prefs"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
      qc.invalidateQueries({ queryKey: ["mc-kanban"] });
      qc.invalidateQueries({ queryKey: ["mc-journal"] });
      qc.invalidateQueries({ queryKey: ["mc-memory"] });
    },
  });
}
