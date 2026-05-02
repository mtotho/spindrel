import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { AttentionCommandDeck } from "@/src/components/attention/AttentionCommandDeck";
import { useWorkspaceAttention, useMarkAttentionResponded, type AttentionTargetKind, type WorkspaceAttentionItem } from "@/src/api/hooks/useWorkspaceAttention";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useDraftsStore } from "@/src/stores/drafts";
import type { AttentionDeckMode } from "@/src/lib/hubRoutes";

function readDeckMode(value: string | null): AttentionDeckMode | null {
  return value === "review" || value === "issues" || value === "inbox" || value === "runs" || value === "cleared" ? value : null;
}

export default function HubAttentionPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedChannelId = searchParams.get("channel");
  const requestedTargetKind = searchParams.get("target_kind") as AttentionTargetKind | null;
  const requestedTargetId = searchParams.get("target_id");
  const requestedRunId = searchParams.get("run");
  const requestedMode = readDeckMode(searchParams.get("mode")) ?? (requestedRunId ? "runs" : null);
  const attentionQuery = useWorkspaceAttention(requestedChannelId || undefined);
  const { data: items = [] } = attentionQuery;
  const attentionLoading = attentionQuery.isLoading || (attentionQuery.isFetching && !attentionQuery.data);
  const { data: channels = [] } = useChannels();
  const markAttentionResponded = useMarkAttentionResponded();
  const requestedItemId = searchParams.get("item");
  const [selectedId, setSelectedId] = useState<string | null>(requestedItemId);
  const filteredItems = useMemo(() => {
    if (!requestedTargetKind || !requestedTargetId) return items;
    return items.filter((item) => {
      if (item.target_kind === requestedTargetKind && item.target_id === requestedTargetId) return true;
      if (requestedTargetKind === "channel" && (item.channel_id === requestedTargetId || item.target_id === requestedTargetId)) return true;
      return false;
    });
  }, [items, requestedTargetId, requestedTargetKind]);
  const channelById = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel])),
    [channels],
  );

  useEffect(() => {
    setSelectedId(requestedItemId);
  }, [requestedItemId]);

  useEffect(() => {
    if (requestedMode === "runs" || requestedMode === "issues" || requestedMode === "cleared" || requestedItemId || selectedId || !filteredItems.length) return;
    setSelectedId(filteredItems[0].id);
  }, [filteredItems, requestedItemId, requestedMode, selectedId]);

  const selectItem = (item: WorkspaceAttentionItem | null) => {
    setSelectedId(item?.id ?? null);
    const next = new URLSearchParams(searchParams);
    if (item) next.set("item", item.id);
    else next.delete("item");
    setSearchParams(next, { replace: true });
  };

  const selectMode = (mode: AttentionDeckMode) => {
    setSelectedId(null);
    const next = new URLSearchParams(searchParams);
    next.set("mode", mode);
    next.delete("item");
    if (mode !== "runs") next.delete("run");
    setSearchParams(next, { replace: true });
  };

  const selectRun = (runId: string | null) => {
    const next = new URLSearchParams(searchParams);
    next.set("mode", "runs");
    next.delete("item");
    if (runId) next.set("run", runId);
    else next.delete("run");
    setSearchParams(next, { replace: true });
  };

  const replyToItem = (item: WorkspaceAttentionItem) => {
    if (!item.channel_id) return;
    const channel = channelById.get(item.channel_id);
    if (!channel) return;
    const draft = [
      `Re: ${item.title}`,
      "",
      item.message,
      "",
      "My response:",
    ].join("\n");
    useDraftsStore.getState().setDraftText(item.channel_id, draft);
    markAttentionResponded.mutate(item.id);
    navigate(`/channels/${item.channel_id}`);
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Hub"
        title="Mission Control Review"
        subtitle="Review findings, sweep raw signals, and inspect receipts"
        backTo="/"
        chrome="flow"
        showMenuWithBack
      />
      <main className="min-h-0 flex-1 px-4 py-4 sm:px-6 lg:px-8 lg:py-5">
        <div className="flex h-full w-full max-w-[1600px] flex-col overflow-hidden rounded-md bg-surface-raised/55">
          <AttentionCommandDeck
            loading={attentionLoading}
            items={filteredItems}
            selectedId={selectedId}
            onSelect={selectItem}
            initialMode={requestedMode}
            selectedRunId={requestedRunId}
            channelId={requestedChannelId}
            onModeChange={selectMode}
            onRunSelect={selectRun}
            onReply={replyToItem}
          />
        </div>
      </main>
    </div>
  );
}
