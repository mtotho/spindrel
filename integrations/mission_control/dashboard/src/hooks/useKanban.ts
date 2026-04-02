import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchFileContent, writeFileContent } from "../lib/api";
import { parseTasksMd, serializeTasksMd } from "../lib/parser";
import type { KanbanColumn } from "../lib/types";

export function useKanban(channelId: string | undefined) {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["kanban", channelId],
    queryFn: async () => {
      const content = await fetchFileContent(channelId!, "tasks.md");
      return parseTasksMd(content);
    },
    enabled: !!channelId,
  });

  const mutation = useMutation({
    mutationFn: async (columns: KanbanColumn[]) => {
      const content = serializeTasksMd(columns);
      await writeFileContent(channelId!, "tasks.md", content);
    },
    onMutate: async (newColumns) => {
      // Cancel outgoing refetches so they don't overwrite our optimistic update
      await queryClient.cancelQueries({ queryKey: ["kanban", channelId] });
      const previous = queryClient.getQueryData<KanbanColumn[]>(["kanban", channelId]);
      queryClient.setQueryData(["kanban", channelId], newColumns);
      return { previous };
    },
    onError: (_err, _newColumns, context) => {
      // Roll back to previous state on error
      if (context?.previous) {
        queryClient.setQueryData(["kanban", channelId], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["kanban", channelId] });
    },
  });

  return { ...query, saveColumns: mutation.mutateAsync, isSaving: mutation.isPending };
}
