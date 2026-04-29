import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { AttentionCommandDeck } from "@/src/components/attention/AttentionCommandDeck";
import { useWorkspaceAttention, useMarkAttentionResponded, type WorkspaceAttentionItem } from "@/src/api/hooks/useWorkspaceAttention";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useDraftsStore } from "@/src/stores/drafts";
import type { AttentionDeckMode } from "@/src/lib/hubRoutes";

function readDeckMode(value: string | null): AttentionDeckMode | null {
  return value === "review" || value === "inbox" || value === "runs" || value === "cleared" ? value : null;
}

export default function HubAttentionPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedChannelId = searchParams.get("channel");
  const requestedMode = readDeckMode(searchParams.get("mode"));
  const { data: items = [] } = useWorkspaceAttention(requestedChannelId || undefined);
  const { data: channels = [] } = useChannels();
  const markAttentionResponded = useMarkAttentionResponded();
  const requestedItemId = searchParams.get("item");
  const [selectedId, setSelectedId] = useState<string | null>(requestedItemId);
  const channelById = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel])),
    [channels],
  );

  useEffect(() => {
    setSelectedId(requestedItemId);
  }, [requestedItemId]);

  const selectItem = (item: WorkspaceAttentionItem | null) => {
    setSelectedId(item?.id ?? null);
    const next = new URLSearchParams(searchParams);
    if (item) next.set("item", item.id);
    else next.delete("item");
    setSearchParams(next, { replace: true });
  };

  const selectMode = (mode: AttentionDeckMode) => {
    const next = new URLSearchParams(searchParams);
    next.set("mode", mode);
    if (mode === "runs") next.delete("item");
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
        title="Attention"
        subtitle="Review findings, sweep raw signals, and inspect run evidence"
        backTo="/"
        chrome="flow"
        showMenuWithBack
      />
      <main className="min-h-0 flex-1 px-2 pb-2 md:px-4 md:pb-4">
        <div className="mx-auto flex h-full max-w-7xl flex-col overflow-hidden rounded-md bg-surface-raised/55">
          <AttentionCommandDeck
            items={items}
            selectedId={selectedId}
            onSelect={selectItem}
            initialMode={requestedMode}
            channelId={requestedChannelId}
            onModeChange={selectMode}
            onReply={replyToItem}
          />
        </div>
      </main>
    </div>
  );
}
