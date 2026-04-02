/**
 * React Query hooks for all Mission Control API endpoints.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchJournal,
  fetchTimeline,
  fetchMemory,
  fetchReferenceFile,
  searchMemory,
  fetchPlans,
  fetchPlan,
  createPlan,
  updatePlan,
  deletePlan,
  approvePlan,
  rejectPlan,
  resumePlan,
  approveStep,
  skipStep,
  fetchPrefs,
  updatePrefs,
  fetchReadiness,
  fetchSetupGuide,
  fetchChannelContext,
  joinChannel,
  leaveChannel,
  fetchKanban,
  kanbanMove,
  kanbanCreate,
  kanbanUpdate,
} from "../lib/api";
import type { MCPrefs } from "../lib/types";

// ---------------------------------------------------------------------------
// Journal
// ---------------------------------------------------------------------------

export function useJournal(days = 7, scope?: string) {
  return useQuery({
    queryKey: ["journal", days, scope],
    queryFn: () => fetchJournal(days, scope),
  });
}

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

export function useTimeline(days = 7, scope?: string) {
  return useQuery({
    queryKey: ["timeline", days, scope],
    queryFn: () => fetchTimeline(days, scope),
  });
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export function useMemory(scope?: string) {
  return useQuery({
    queryKey: ["memory", scope],
    queryFn: () => fetchMemory(scope),
  });
}

export function useReferenceFile(botId?: string, filename?: string) {
  return useQuery({
    queryKey: ["reference-file", botId, filename],
    queryFn: () => fetchReferenceFile(botId!, filename!),
    enabled: !!botId && !!filename,
  });
}

export function useMemorySearch() {
  return useMutation({
    mutationFn: (args: { query: string; scope?: string; topK?: number }) =>
      searchMemory(args.query, args.scope, args.topK),
  });
}

// ---------------------------------------------------------------------------
// Plans
// ---------------------------------------------------------------------------

export function usePlans(scope?: string, status?: string) {
  return useQuery({
    queryKey: ["plans", scope, status],
    queryFn: () => fetchPlans(scope, status),
  });
}

export function usePlan(channelId?: string, planId?: string) {
  return useQuery({
    queryKey: ["plan", channelId, planId],
    queryFn: () => fetchPlan(channelId!, planId!),
    enabled: !!channelId && !!planId,
  });
}

export function usePlanCreate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      channelId: string;
      title: string;
      notes?: string;
      steps: Array<{ content: string; requires_approval?: boolean }>;
    }) => createPlan(args.channelId, { title: args.title, notes: args.notes, steps: args.steps }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}

export function usePlanUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      channelId: string;
      planId: string;
      title?: string;
      notes?: string;
      steps?: Array<{ content: string; requires_approval?: boolean }>;
    }) => updatePlan(args.channelId, args.planId, { title: args.title, notes: args.notes, steps: args.steps }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
    },
  });
}

export function usePlanDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { channelId: string; planId: string }) =>
      deletePlan(args.channelId, args.planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}

export function usePlanApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { channelId: string; planId: string }) =>
      approvePlan(args.channelId, args.planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}

export function usePlanReject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { channelId: string; planId: string }) =>
      rejectPlan(args.channelId, args.planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
    },
  });
}

export function usePlanResume() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { channelId: string; planId: string }) =>
      resumePlan(args.channelId, args.planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
    },
  });
}

export function useStepApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { channelId: string; planId: string; position: number }) =>
      approveStep(args.channelId, args.planId, args.position),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
    },
  });
}

export function useStepSkip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { channelId: string; planId: string; position: number }) =>
      skipStep(args.channelId, args.planId, args.position),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["plan"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Aggregated Kanban
// ---------------------------------------------------------------------------

export function useAggregatedKanban(scope?: string) {
  return useQuery({
    queryKey: ["kanban-agg", scope],
    queryFn: () => fetchKanban(scope),
  });
}

export function useKanbanMove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: kanbanMove,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kanban-agg"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      qc.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
}

export function useKanbanCreate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: kanbanCreate,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kanban-agg"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      qc.invalidateQueries({ queryKey: ["timeline"] });
    },
  });
}

export function useKanbanUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: kanbanUpdate,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kanban-agg"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Preferences
// ---------------------------------------------------------------------------

export function usePrefs() {
  return useQuery({
    queryKey: ["prefs"],
    queryFn: fetchPrefs,
  });
}

export function useUpdatePrefs() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<MCPrefs>) => updatePrefs(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prefs"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      qc.invalidateQueries({ queryKey: ["kanban-agg"] });
      qc.invalidateQueries({ queryKey: ["journal"] });
      qc.invalidateQueries({ queryKey: ["memory"] });
      qc.invalidateQueries({ queryKey: ["timeline"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Readiness / Setup
// ---------------------------------------------------------------------------

export function useReadiness() {
  return useQuery({
    queryKey: ["readiness"],
    queryFn: fetchReadiness,
    staleTime: 60_000,
  });
}

export function useSetupGuide() {
  return useQuery({
    queryKey: ["setup-guide"],
    queryFn: fetchSetupGuide,
    staleTime: 300_000,
  });
}

// ---------------------------------------------------------------------------
// Channel context (debug)
// ---------------------------------------------------------------------------

export function useChannelContext(channelId?: string) {
  return useQuery({
    queryKey: ["channel-context", channelId],
    queryFn: () => fetchChannelContext(channelId!),
    enabled: !!channelId,
  });
}

// ---------------------------------------------------------------------------
// Channel membership
// ---------------------------------------------------------------------------

export function useJoinChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: joinChannel,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}

export function useLeaveChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: leaveChannel,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
  });
}
