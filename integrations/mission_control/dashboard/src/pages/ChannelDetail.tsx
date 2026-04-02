import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useChannelFiles, useFileContent, useDailyLogs } from "../hooks/useChannelFiles";
import { useKanban } from "../hooks/useKanban";
import { useOverview } from "../hooks/useOverview";
import KanbanBoard from "../components/KanbanBoard";
import MarkdownViewer from "../components/MarkdownViewer";
import EmptyState from "../components/EmptyState";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import { generateCardId } from "../lib/parser";
import type { KanbanColumn } from "../lib/types";

type Tab = "files" | "kanban" | "activity";

export default function ChannelDetail() {
  const { channelId } = useParams<{ channelId: string }>();
  const [activeTab, setActiveTab] = useState<Tab>("files");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const { data: overview } = useOverview();
  const channel = overview?.channels.find((ch) => ch.id === channelId);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <Link to="/" className="text-xs text-gray-500 hover:text-gray-400 transition-colors">
          &larr; Overview
        </Link>
        <h1 className="text-2xl font-bold text-gray-100 mt-1" title={channelId}>
          {channel?.name || channelId?.slice(0, 8)}
        </h1>
        <div className="flex items-center gap-3 mt-0.5">
          {channel?.bot_id && (
            <p className="text-sm text-gray-500">{channel.bot_id}</p>
          )}
          {channelId && (
            <Link
              to={`/channels/${channelId}/kanban`}
              className="text-xs text-accent hover:text-accent-hover transition-colors"
            >
              Open full kanban &rarr;
            </Link>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-surface-3">
        {(["files", "kanban", "activity"] as Tab[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm capitalize transition-colors border-b-2 -mb-px ${
              activeTab === tab
                ? "border-accent text-accent-hover"
                : "border-transparent text-gray-500 hover:text-gray-300"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "files" && channelId && (
        <FilesTab channelId={channelId} selectedFile={selectedFile} onSelectFile={setSelectedFile} />
      )}
      {activeTab === "kanban" && channelId && (
        <KanbanTab channelId={channelId} />
      )}
      {activeTab === "activity" && channelId && (
        <ActivityTab channelId={channelId} />
      )}
    </div>
  );
}

function FilesTab({
  channelId,
  selectedFile,
  onSelectFile,
}: {
  channelId: string;
  selectedFile: string | null;
  onSelectFile: (path: string | null) => void;
}) {
  const { data: files, isLoading, error, refetch } = useChannelFiles(channelId);
  const { data: content, isLoading: loadingContent } = useFileContent(
    channelId,
    selectedFile ?? undefined,
  );

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error.message} onRetry={() => refetch()} />;

  if (!files?.length) {
    return (
      <EmptyState
        icon="◇"
        title="No workspace files yet"
        description="Send a message to this channel's bot to get started. The bot will create workspace files based on the channel's schema."
      />
    );
  }

  return (
    <div className="flex gap-4">
      {/* File list */}
      <div className="w-48 flex-shrink-0 space-y-0.5 overflow-y-auto max-h-[calc(100vh-16rem)]">
        {files.map((f) => (
          <button
            key={f.path}
            onClick={() => onSelectFile(f.path)}
            title={f.name}
            className={`w-full text-left px-3 py-1.5 rounded text-sm transition-colors truncate ${
              selectedFile === f.path
                ? "bg-accent/15 text-accent-hover"
                : "text-gray-400 hover:text-gray-200 hover:bg-surface-3"
            }`}
          >
            {f.name}
          </button>
        ))}
      </div>

      {/* File content */}
      <div className="flex-1 min-w-0 bg-surface-1 rounded-xl border border-surface-3 p-4 overflow-y-auto max-h-[calc(100vh-16rem)]">
        {selectedFile ? (
          loadingContent ? (
            <LoadingSpinner />
          ) : content ? (
            <MarkdownViewer content={content} />
          ) : (
            <EmptyState icon="◇" title="File not found" description="This file may have been moved or deleted." />
          )
        ) : (
          <div className="flex items-center justify-center h-full min-h-[200px]">
            <p className="text-sm text-gray-600">Select a file from the sidebar to view its contents.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function KanbanTab({ channelId }: { channelId: string }) {
  const { data: columns, isLoading, error, saveColumns, isSaving } = useKanban(channelId);

  if (isLoading) return <LoadingSpinner />;

  if (error) {
    if (error.message.includes("404")) {
      return (
        <EmptyState
          icon="▦"
          title="No kanban board yet"
          description="This channel doesn't have a tasks.md file. Ask your bot to create one, or use the create_task_card tool."
        />
      );
    }
    return <ErrorBanner message={error.message} />;
  }

  if (!columns?.length) {
    return (
      <EmptyState
        icon="▦"
        title="Empty kanban board"
        description="The tasks.md file exists but has no columns. Ask your bot to add tasks, or create one from the full kanban view."
      />
    );
  }

  const handleMove = async (cardId: string, fromCol: string, toCol: string) => {
    const movedCard = columns
      .find((c) => c.name === fromCol)
      ?.cards.find((c) => (c.meta.id || c.title) === cardId);
    if (!movedCard) return;

    const updated: KanbanColumn[] = columns.map((col) => {
      if (col.name === fromCol) {
        return { ...col, cards: col.cards.filter((c) => (c.meta.id || c.title) !== cardId) };
      }
      if (col.name === toCol) {
        return { ...col, cards: [...col.cards, movedCard] };
      }
      return col;
    });
    await saveColumns(updated);
  };

  const handleAddCard = async (
    columnName: string,
    card: { title: string; priority: string; description: string },
  ) => {
    const today = new Date().toISOString().slice(0, 10);
    const newCard = {
      title: card.title,
      meta: { id: generateCardId(), priority: card.priority, created: today },
      description: card.description,
    };
    const updated: KanbanColumn[] = columns.map((col) => {
      if (col.name === columnName) {
        return { ...col, cards: [...col.cards, newCard] };
      }
      return col;
    });
    await saveColumns(updated);
  };

  return <KanbanBoard columns={columns} onMove={handleMove} onAddCard={handleAddCard} isSaving={isSaving} />;
}

function ActivityTab({ channelId }: { channelId: string }) {
  const { data: logs, isLoading } = useDailyLogs(channelId, 14);

  if (isLoading) return <LoadingSpinner />;

  if (!logs?.length) {
    return (
      <EmptyState
        icon="◉"
        title="No activity logs yet"
        description="Daily logs will appear here as the bot works in this channel. Logs are stored at memory/logs/YYYY-MM-DD.md."
      />
    );
  }

  return (
    <div className="space-y-4">
      {logs.map((log) => (
        <div key={`${channelId}-${log.date}`} className="bg-surface-1 rounded-xl border border-surface-3 p-4">
          <h3 className="text-sm font-medium text-gray-200 mb-2">{log.date}</h3>
          <MarkdownViewer content={log.content} />
        </div>
      ))}
    </div>
  );
}
