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
  is_member: boolean;
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
  total_channels_all: number;
  total_bots: number;
  total_tasks: number;
  is_admin: boolean;
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

export interface MCTimelineEvent {
  date: string;
  time: string;
  event: string;
  channel_id: string;
  channel_name: string;
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

export interface MCPlanStep {
  position: number;
  status: string;
  content: string;
  requires_approval: boolean;
  task_id: string | null;
  result_summary: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface MCPlan {
  id: string;
  title: string;
  status: string;
  meta: Record<string, string>;
  steps: MCPlanStep[];
  notes: string;
  channel_id: string;
  channel_name: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface MCFeatureReadiness {
  ready: boolean;
  detail: string;
  count: number;
  total: number;
  issues: string[];
}

export interface MCReadiness {
  dashboard: MCFeatureReadiness;
  kanban: MCFeatureReadiness;
  journal: MCFeatureReadiness;
  memory: MCFeatureReadiness;
  timeline: MCFeatureReadiness;
  plans: MCFeatureReadiness;
}

export interface MCDashboardModule {
  integration_id: string;
  module_id: string;
  label: string;
  icon: string;
  description: string;
  api_base: string;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useMCOverview(scope?: "fleet" | "personal") {
  return useQuery({
    queryKey: ["mc-overview", scope],
    queryFn: () =>
      apiFetch<MCOverview>(
        `/integrations/mission_control/overview${scope ? `?scope=${scope}` : ""}`
      ),
  });
}

export function useMCKanban(scope?: "fleet" | "personal") {
  return useQuery({
    queryKey: ["mc-kanban", scope],
    queryFn: () =>
      apiFetch<MCKanbanResponse>(
        `/integrations/mission_control/kanban${scope ? `?scope=${scope}` : ""}`
      ),
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
      apiFetch("/integrations/mission_control/kanban/move", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-kanban"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
    },
  });
}

export function useMCKanbanUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      card_id: string;
      channel_id: string;
      title?: string;
      description?: string;
      priority?: string;
      assigned?: string;
      due?: string;
      tags?: string;
    }) =>
      apiFetch("/integrations/mission_control/kanban/update", {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-kanban"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
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
      apiFetch("/integrations/mission_control/kanban/create", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-kanban"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
    },
  });
}

export function useMCJournal(days = 7, scope?: "fleet" | "personal") {
  return useQuery({
    queryKey: ["mc-journal", days, scope],
    queryFn: () => {
      const params = new URLSearchParams({ days: String(days) });
      if (scope) params.set("scope", scope);
      return apiFetch<{ entries: MCJournalEntry[] }>(
        `/integrations/mission_control/journal?${params}`
      );
    },
  });
}

export function useMCTimeline(days = 7, scope?: "fleet" | "personal") {
  return useQuery({
    queryKey: ["mc-timeline", days, scope],
    queryFn: () => {
      const params = new URLSearchParams({ days: String(days) });
      if (scope) params.set("scope", scope);
      return apiFetch<{ events: MCTimelineEvent[] }>(
        `/integrations/mission_control/timeline?${params}`
      );
    },
  });
}

export function useMCMemory(scope?: "fleet" | "personal") {
  return useQuery({
    queryKey: ["mc-memory", scope],
    queryFn: () =>
      apiFetch<{ sections: MCMemorySection[] }>(
        `/integrations/mission_control/memory${scope ? `?scope=${scope}` : ""}`
      ),
  });
}

export function useMCChannelContext(channelId: string | undefined) {
  return useQuery({
    queryKey: ["mc-channel-context", channelId],
    queryFn: () =>
      apiFetch<MCChannelContext>(
        `/integrations/mission_control/channels/${channelId}/context`
      ),
    enabled: !!channelId,
  });
}

export function useMCPrefs() {
  return useQuery({
    queryKey: ["mc-prefs"],
    queryFn: () => apiFetch<MCPrefs>("/integrations/mission_control/prefs"),
  });
}

export function useUpdateMCPrefs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<MCPrefs>) =>
      apiFetch<MCPrefs>("/integrations/mission_control/prefs", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-prefs"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
      qc.invalidateQueries({ queryKey: ["mc-kanban"] });
      qc.invalidateQueries({ queryKey: ["mc-journal"] });
      qc.invalidateQueries({ queryKey: ["mc-memory"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
    },
  });
}

export function useMCReadiness() {
  return useQuery({
    queryKey: ["mc-readiness"],
    queryFn: () =>
      apiFetch<MCReadiness>("/integrations/mission_control/readiness"),
    staleTime: 60_000,
  });
}

export function useMCReferenceFile(
  botId: string | undefined,
  filename: string | undefined
) {
  return useQuery({
    queryKey: ["mc-reference-file", botId, filename],
    queryFn: () =>
      apiFetch<{ content: string }>(
        `/integrations/mission_control/memory/${botId}/reference/${filename}`
      ),
    enabled: !!botId && !!filename,
  });
}

export function useMCModules() {
  return useQuery({
    queryKey: ["mc-modules"],
    queryFn: () =>
      apiFetch<{ modules: MCDashboardModule[] }>(
        "/integrations/mission_control/modules"
      ),
    staleTime: 300_000,
  });
}

export function useMCPlans(scope?: "fleet" | "personal", status?: string) {
  return useQuery({
    queryKey: ["mc-plans", scope, status],
    queryFn: () => {
      const params = new URLSearchParams();
      if (scope) params.set("scope", scope);
      if (status) params.set("status", status);
      const qs = params.toString();
      return apiFetch<{ plans: MCPlan[] }>(
        `/integrations/mission_control/plans${qs ? `?${qs}` : ""}`
      );
    },
  });
}

export function useMCPlanApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      planId,
    }: {
      channelId: string;
      planId: string;
    }) =>
      apiFetch(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}/approve`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-plans"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
      qc.invalidateQueries({ queryKey: ["mc-readiness"] });
    },
  });
}

export function useMCPlanReject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      planId,
    }: {
      channelId: string;
      planId: string;
    }) =>
      apiFetch(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}/reject`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-plans"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
      qc.invalidateQueries({ queryKey: ["mc-readiness"] });
    },
  });
}

export function useMCPlanResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      planId,
    }: {
      channelId: string;
      planId: string;
    }) =>
      apiFetch(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}/resume`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-plans"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
    },
  });
}

export function useMCPlanStepApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      planId,
      position,
    }: {
      channelId: string;
      planId: string;
      position: number;
    }) =>
      apiFetch(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}/steps/${position}/approve`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-plans"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
    },
  });
}

export function useMCPlan(channelId: string | undefined, planId: string | undefined) {
  return useQuery({
    queryKey: ["mc-plan", channelId, planId],
    queryFn: () =>
      apiFetch<MCPlan>(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}`
      ),
    enabled: !!channelId && !!planId,
  });
}

export function useMCPlanCreate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      title,
      notes,
      steps,
    }: {
      channelId: string;
      title: string;
      notes?: string;
      steps: Array<{ content: string; requires_approval?: boolean }>;
    }) =>
      apiFetch<{ ok: boolean; plan_id: string; status: string }>(
        `/integrations/mission_control/channels/${channelId}/plans`,
        {
          method: "POST",
          body: JSON.stringify({ title, notes: notes || "", steps }),
        }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-plans"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
    },
  });
}

export function useMCPlanUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      planId,
      title,
      notes,
      steps,
    }: {
      channelId: string;
      planId: string;
      title?: string;
      notes?: string;
      steps?: Array<{ content: string; requires_approval?: boolean }>;
    }) =>
      apiFetch(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ title, notes, steps }),
        }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-plans"] });
      qc.invalidateQueries({ queryKey: ["mc-plan"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
    },
  });
}

export function useMCPlanStepSkip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      planId,
      position,
    }: {
      channelId: string;
      planId: string;
      position: number;
    }) =>
      apiFetch(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}/steps/${position}/skip`,
        { method: "POST" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-plans"] });
      qc.invalidateQueries({ queryKey: ["mc-plan"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
    },
  });
}

export function useMCPlanDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      planId,
    }: {
      channelId: string;
      planId: string;
    }) =>
      apiFetch(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}`,
        { method: "DELETE" }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-plans"] });
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
      qc.invalidateQueries({ queryKey: ["mc-timeline"] });
    },
  });
}

export function useJoinChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (channelId: string) =>
      apiFetch(`/integrations/mission_control/channels/${channelId}/join`, {
        method: "POST",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
    },
  });
}

export function useLeaveChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (channelId: string) =>
      apiFetch(`/integrations/mission_control/channels/${channelId}/join`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mc-overview"] });
    },
  });
}
