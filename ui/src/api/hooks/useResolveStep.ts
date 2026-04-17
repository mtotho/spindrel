import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../client";

interface ResolveArgs {
  taskId: string;
  stepIndex: number;
  response: Record<string, any>;
}

export function useResolveStep() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, stepIndex, response }: ResolveArgs) =>
      apiFetch(`/api/v1/admin/tasks/${taskId}/steps/${stepIndex}/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ response }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["findings"] });
      qc.invalidateQueries({ queryKey: ["admin-tasks-timeline"] });
      qc.invalidateQueries({ queryKey: ["orchestrator-runs"] });
      qc.invalidateQueries({ queryKey: ["channel-messages"] });
    },
  });
}
