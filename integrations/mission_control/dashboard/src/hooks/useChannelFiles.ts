import { useQuery } from "@tanstack/react-query";
import { fetchChannelFiles, fetchFileContent, fetchDailyLogs } from "../lib/api";

export function useChannelFiles(channelId: string | undefined) {
  return useQuery({
    queryKey: ["channelFiles", channelId],
    queryFn: () => fetchChannelFiles(channelId!),
    enabled: !!channelId,
  });
}

export function useFileContent(channelId: string | undefined, path: string | undefined) {
  return useQuery({
    queryKey: ["fileContent", channelId, path],
    queryFn: () => fetchFileContent(channelId!, path!),
    enabled: !!channelId && !!path,
  });
}

export function useDailyLogs(channelId: string | undefined, limit = 7) {
  return useQuery({
    queryKey: ["dailyLogs", channelId, limit],
    queryFn: () => fetchDailyLogs(channelId!, limit),
    enabled: !!channelId,
  });
}
