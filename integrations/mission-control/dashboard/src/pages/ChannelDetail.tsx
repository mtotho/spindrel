import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useChannelFiles, useFileContent, useDailyLogs } from "../hooks/useChannelFiles";
import { useKanban } from "../hooks/useKanban";
import { useOverview } from "../hooks/useOverview";
import KanbanBoard from "../components/KanbanBoard";
import MarkdownViewer from "../components/MarkdownViewer";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
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
        <h1 className="text-2xl font-bold text-gray-100 mt-1">
          {channel?.name || channelId?.slice(0, 8)}
        </h1>
        {channel?.bot_id && (
          <p className="text-sm text-gray-500">{channel.bot_id}</p>
        )}
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
  const { data: files, isLoading, error } = useChannelFiles(channelId);
  const { data: content, isLoading: loadingContent } = useFileContent(
    channelId,
    selectedFile ?? undefined,
  );

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error.message} />;
  if (!files?.length) return <p className="text-sm text-gray-500">No workspace files.</p>;

  return (
    <div className="flex gap-4">
      {/* File list */}
      <div className="w-48 flex-shrink-0 space-y-0.5">
        {files.map((f) => (
          <button
            key={f.path}
            onClick={() => onSelectFile(f.path)}
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
      <div className="flex-1 min-w-0 bg-surface-1 rounded-xl border border-surface-3 p-4">
        {selectedFile ? (
          loadingContent ? (
            <LoadingSpinner />
          ) : content ? (
            <MarkdownViewer content={content} />
          ) : (
            <p className="text-sm text-gray-500">File not found.</p>
          )
        ) : (
          <p className="text-sm text-gray-500">Select a file to view.</p>
        )}
      </div>
    </div>
  );
}

function KanbanTab({ channelId }: { channelId: string }) {
  const { data: columns, isLoading, error, saveColumns, isSaving } = useKanban(channelId);

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error.message} />;
  if (!columns) return null;

  const handleMove = async (cardId: string, fromCol: string, toCol: string) => {
    const updated: KanbanColumn[] = columns.map((col) => {
      if (col.name === fromCol) {
        return { ...col, cards: col.cards.filter((c) => c.meta.id !== cardId) };
      }
      if (col.name === toCol) {
        const card = columns
          .find((c) => c.name === fromCol)
          ?.cards.find((c) => c.meta.id === cardId);
        if (card) {
          return { ...col, cards: [...col.cards, card] };
        }
      }
      return col;
    });
    await saveColumns(updated);
  };

  return <KanbanBoard columns={columns} onMove={handleMove} isSaving={isSaving} />;
}

function ActivityTab({ channelId }: { channelId: string }) {
  const { data: logs, isLoading } = useDailyLogs(channelId, 14);

  if (isLoading) return <LoadingSpinner />;
  if (!logs?.length) return <p className="text-sm text-gray-500">No activity logs found.</p>;

  return (
    <div className="space-y-4">
      {logs.map((log) => (
        <div key={log.date} className="bg-surface-1 rounded-xl border border-surface-3 p-4">
          <h3 className="text-sm font-medium text-gray-200 mb-2">{log.date}</h3>
          <MarkdownViewer content={log.content} />
        </div>
      ))}
    </div>
  );
}
