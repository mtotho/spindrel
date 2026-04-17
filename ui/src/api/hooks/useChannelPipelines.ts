import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

export interface PipelineDef {
  id: string;
  title?: string | null;
  bot_id: string;
  source: "user" | "system";
  task_type: string;
  description?: string | null;
  featured?: boolean;
  params_schema?: Array<{ name: string; required?: boolean; description?: string }> | null;
  requires_channel?: boolean;
  requires_bot?: boolean;
}

export interface ChannelPipelineSubscription {
  id: string;
  channel_id: string;
  task_id: string;
  enabled: boolean;
  featured_override: boolean | null;
  /** resolved: featured_override ?? pipeline.execution_config.featured */
  featured: boolean;
  schedule: string | null;
  schedule_config: Record<string, any> | null;
  last_fired_at: string | null;
  next_fire_at: string | null;
  created_at: string;
  updated_at: string;
  pipeline: PipelineDef | null;
}

export interface TaskSubscription extends ChannelPipelineSubscription {
  channel: { id: string; name: string | null; client_id: string | null };
}

export interface SubscribeInput {
  task_id: string;
  enabled?: boolean;
  featured_override?: boolean | null;
  schedule?: string | null;
  schedule_config?: Record<string, any> | null;
}

export interface SubscriptionPatch {
  enabled?: boolean;
  featured_override?: boolean | null;
  schedule?: string | null;
  schedule_config?: Record<string, any> | null;
  clear_schedule?: boolean;
}

// ---------------------------------------------------------------------------
// Channel-scoped
// ---------------------------------------------------------------------------

export function useChannelPipelines(
  channelId: string | undefined,
  opts?: { enabledOnly?: boolean; refetchInterval?: number | false },
) {
  const qs = opts?.enabledOnly ? "?enabled=true" : "";
  return useQuery({
    queryKey: ["channel-pipelines", channelId, opts?.enabledOnly ?? false],
    queryFn: () =>
      apiFetch<{ subscriptions: ChannelPipelineSubscription[] }>(
        `/api/v1/admin/channels/${channelId}/pipelines${qs}`,
      ),
    enabled: !!channelId,
    refetchInterval: opts?.refetchInterval ?? false,
  });
}

export function useSubscribePipeline(channelId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SubscribeInput) =>
      apiFetch<ChannelPipelineSubscription>(
        `/api/v1/admin/channels/${channelId}/pipelines`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-pipelines", channelId] });
      qc.invalidateQueries({ queryKey: ["task-subscriptions"] });
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
    },
  });
}

export function useUpdateSubscription(channelId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      subscriptionId,
      patch,
    }: {
      subscriptionId: string;
      patch: SubscriptionPatch;
    }) =>
      apiFetch<ChannelPipelineSubscription>(
        `/api/v1/admin/channels/${channelId}/pipelines/${subscriptionId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-pipelines", channelId] });
      qc.invalidateQueries({ queryKey: ["task-subscriptions"] });
    },
  });
}

export function useUnsubscribePipeline(channelId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (subscriptionId: string) =>
      apiFetch(
        `/api/v1/admin/channels/${channelId}/pipelines/${subscriptionId}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["channel-pipelines", channelId] });
      qc.invalidateQueries({ queryKey: ["task-subscriptions"] });
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Task-scoped mirror
// ---------------------------------------------------------------------------

export function useTaskSubscriptions(taskId: string | undefined) {
  return useQuery({
    queryKey: ["task-subscriptions", taskId],
    queryFn: () =>
      apiFetch<{ subscriptions: TaskSubscription[] }>(
        `/api/v1/admin/tasks/${taskId}/subscriptions`,
      ),
    enabled: !!taskId,
  });
}
