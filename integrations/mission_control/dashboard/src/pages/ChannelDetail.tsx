import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useChannelFiles, useFileContent, useDailyLogs } from "../hooks/useChannelFiles";
import { useKanban } from "../hooks/useKanban";
import { useOverview } from "../hooks/useOverview";
import { useChannelContext, useJoinChannel, useLeaveChannel } from "../hooks/useMC";
import KanbanBoard from "../components/KanbanBoard";
import MarkdownViewer from "../components/MarkdownViewer";
import EmptyState from "../components/EmptyState";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import { generateCardId } from "../lib/parser";
import type { KanbanColumn, ChannelContext } from "../lib/types";

type Tab = "files" | "kanban" | "activity" | "context";

export default function ChannelDetail() {
  const { channelId } = useParams<{ channelId: string }>();
  const [activeTab, setActiveTab] = useState<Tab>("files");

  const { data: overview } = useOverview();
  const channel = overview?.channels.find((ch) => ch.id === channelId);
  const join = useJoinChannel();
  const leave = useLeaveChannel();

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-6">
        <Link to="/" className="text-xs text-gray-500 hover:text-gray-400 transition-colors">
          &larr; Overview
        </Link>
        <div className="flex items-center gap-3 mt-1">
          <h1 className="text-2xl font-bold text-gray-100" title={channelId}>
            {channel?.name || channelId?.slice(0, 8)}
          </h1>
          {channel && (
            <button
              onClick={() =>
                channel.is_member
                  ? leave.mutate(channel.id)
                  : join.mutate(channel.id)
              }
              disabled={join.isPending || leave.isPending}
              className={`px-2.5 py-1 text-[10px] rounded-full transition-colors ${
                channel.is_member
                  ? "bg-green-500/15 text-green-400 hover:bg-red-500/15 hover:text-red-400"
                  : "bg-surface-3 text-gray-400 hover:bg-accent/15 hover:text-accent-hover"
              }`}
            >
              {channel.is_member ? "Joined" : "Join"}
            </button>
          )}
        </div>
        <div className="flex items-center gap-3 mt-0.5">
          {channel?.bot_name && (
            <p className="text-sm text-gray-500">{channel.bot_name}</p>
          )}
          {channelId && (
            <Link
              to="/kanban"
              className="text-xs text-accent hover:text-accent-hover transition-colors"
            >
              Open full kanban &rarr;
            </Link>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-surface-3">
        {(["files", "kanban", "activity", "context"] as Tab[]).map((tab) => (
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
        <FilesTab channelId={channelId} />
      )}
      {activeTab === "kanban" && channelId && (
        <KanbanTab channelId={channelId} />
      )}
      {activeTab === "activity" && channelId && (
        <ActivityTab channelId={channelId} />
      )}
      {activeTab === "context" && channelId && (
        <ContextTab channelId={channelId} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Files tab
// ---------------------------------------------------------------------------
function FilesTab({ channelId }: { channelId: string }) {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
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
        icon="\u25C7"
        title="No workspace files yet"
        description="Send a message to this channel's bot to get started."
      />
    );
  }

  return (
    <div className="flex gap-4">
      <div className="w-48 flex-shrink-0 space-y-0.5 overflow-y-auto max-h-[calc(100vh-16rem)]">
        {files.map((f) => (
          <button
            key={f.path}
            onClick={() => setSelectedFile(f.path)}
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
      <div className="flex-1 min-w-0 bg-surface-1 rounded-xl border border-surface-3 p-4 overflow-y-auto max-h-[calc(100vh-16rem)]">
        {selectedFile ? (
          loadingContent ? (
            <LoadingSpinner />
          ) : content ? (
            <MarkdownViewer content={content} />
          ) : (
            <EmptyState icon="\u25C7" title="File not found" description="This file may have been moved or deleted." />
          )
        ) : (
          <div className="flex items-center justify-center h-full min-h-[200px]">
            <p className="text-sm text-gray-600">Select a file to view.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Kanban tab
// ---------------------------------------------------------------------------
function KanbanTab({ channelId }: { channelId: string }) {
  const { data: columns, isLoading, error, saveColumns, isSaving } = useKanban(channelId);

  if (isLoading) return <LoadingSpinner />;
  if (error) {
    if (error.message.includes("404")) {
      return (
        <EmptyState
          icon="\u25A6"
          title="No kanban board yet"
          description="This channel doesn't have a tasks.md file."
        />
      );
    }
    return <ErrorBanner message={error.message} />;
  }
  if (!columns?.length) {
    return <EmptyState icon="\u25A6" title="Empty kanban board" description="No columns in tasks.md." />;
  }

  const handleMove = async (cardId: string, fromCol: string, toCol: string) => {
    const movedCard = columns.find((c) => c.name === fromCol)?.cards.find((c) => (c.meta.id || c.title) === cardId);
    if (!movedCard) return;
    const updated: KanbanColumn[] = columns.map((col) => {
      if (col.name === fromCol) return { ...col, cards: col.cards.filter((c) => (c.meta.id || c.title) !== cardId) };
      if (col.name === toCol) return { ...col, cards: [...col.cards, movedCard] };
      return col;
    });
    await saveColumns(updated);
  };

  const handleAddCard = async (columnName: string, card: { title: string; priority: string; description: string }) => {
    const newCard = {
      title: card.title,
      meta: { id: generateCardId(), priority: card.priority, created: new Date().toISOString().slice(0, 10) },
      description: card.description,
    };
    const updated: KanbanColumn[] = columns.map((col) => {
      if (col.name === columnName) return { ...col, cards: [...col.cards, newCard] };
      return col;
    });
    await saveColumns(updated);
  };

  return <KanbanBoard columns={columns} onMove={handleMove} onAddCard={handleAddCard} isSaving={isSaving} />;
}

// ---------------------------------------------------------------------------
// Activity tab
// ---------------------------------------------------------------------------
function ActivityTab({ channelId }: { channelId: string }) {
  const { data: logs, isLoading } = useDailyLogs(channelId, 14);

  if (isLoading) return <LoadingSpinner />;
  if (!logs?.length) {
    return <EmptyState icon="\u25C9" title="No activity logs yet" description="Daily logs appear as the bot works." />;
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

// ---------------------------------------------------------------------------
// Context debug tab
// ---------------------------------------------------------------------------
function ContextTab({ channelId }: { channelId: string }) {
  const { data, isLoading, error, refetch } = useChannelContext(channelId);

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorBanner message={error.message} onRetry={() => refetch()} />;
  if (!data) return <EmptyState icon="\u25C7" title="Not found" description="Channel context not available." />;

  return (
    <div className="space-y-4">
      <ContextSection title="Configuration" defaultOpen>
        <div className="space-y-1">
          <ConfigRow label="Channel" value={`${data.config.channel_name} (${data.config.channel_id.slice(0, 8)})`} />
          <ConfigRow label="Bot" value={`${data.config.bot_name} (${data.config.bot_id})`} />
          <ConfigRow label="Model" value={data.config.model} />
          <ConfigRow label="Workspace" value={data.config.workspace_enabled ? "Enabled" : "Disabled"} />
          <ConfigRow label="Workspace RAG" value={data.config.workspace_rag ? "On" : "Off"} />
          <ConfigRow label="Compaction" value={data.config.context_compaction ? "On" : "Off"} />
          <ConfigRow label="Memory Scheme" value={data.config.memory_scheme || "none"} />
          <ConfigRow label="History Mode" value={data.config.history_mode || "default"} />
          <ConfigRow label="Tools" value={data.config.tools.join(", ") || "none"} />
          <ConfigRow label="MCP Servers" value={data.config.mcp_servers.join(", ") || "none"} />
          <ConfigRow label="Skills" value={data.config.skills.join(", ") || "none"} />
          <ConfigRow label="Pinned Tools" value={data.config.pinned_tools.join(", ") || "none"} />
        </div>
      </ContextSection>

      <ContextSection title="Template" badge={data.schema.template_name || undefined}>
        {data.schema.content ? (
          <pre className="text-xs text-gray-400 font-mono whitespace-pre-wrap overflow-x-auto">
            {data.schema.content}
          </pre>
        ) : (
          <p className="text-xs text-gray-500 italic">No template assigned</p>
        )}
      </ContextSection>

      <ContextSection title={`Workspace Files (${data.files.length})`}>
        {data.files.length === 0 ? (
          <p className="text-xs text-gray-500 italic">No workspace files</p>
        ) : (
          <div className="space-y-1">
            {data.files.map((f) => (
              <div key={f.path} className="flex items-center gap-2 text-xs py-1">
                <span className="text-gray-300 flex-1 truncate">{f.name}</span>
                <span className="text-gray-600">{f.section}</span>
                <span className="text-gray-600">{(f.size / 1024).toFixed(1)}KB</span>
              </div>
            ))}
          </div>
        )}
      </ContextSection>

      <ContextSection title={`Tool Calls (${data.tool_calls.length})`}>
        {data.tool_calls.length === 0 ? (
          <p className="text-xs text-gray-500 italic">No recent tool calls</p>
        ) : (
          <div className="space-y-2">
            {data.tool_calls.map((tc) => (
              <ToolCallRow key={tc.id} tc={tc} />
            ))}
          </div>
        )}
      </ContextSection>

      <ContextSection title={`Trace Events (${data.trace_events.length})`}>
        {data.trace_events.length === 0 ? (
          <p className="text-xs text-gray-500 italic">No recent trace events</p>
        ) : (
          <div className="space-y-2">
            {data.trace_events.map((te) => (
              <TraceRow key={te.id} te={te} />
            ))}
          </div>
        )}
      </ContextSection>
    </div>
  );
}

function ContextSection({
  title,
  badge,
  defaultOpen,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen ?? false);
  return (
    <div className="bg-surface-2 rounded-xl border border-surface-3 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-3 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-200">{title}</span>
          {badge && (
            <span className="px-2 py-0.5 rounded-full text-[10px] bg-accent/15 text-accent-hover">
              {badge}
            </span>
          )}
        </div>
        <span className="text-xs text-gray-500">{open ? "\u25B2" : "\u25BC"}</span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 py-1">
      <span className="text-xs text-gray-500 w-28 flex-shrink-0">{label}</span>
      <span className="text-xs text-gray-300 break-all">{value}</span>
    </div>
  );
}

function ToolCallRow({ tc }: { tc: ChannelContext["tool_calls"][0] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className="rounded-lg border border-surface-3 p-3 cursor-pointer hover:bg-surface-1 transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2">
        <span className={`text-xs font-medium ${tc.error ? "text-red-400" : "text-gray-200"}`}>
          {tc.tool_name}
        </span>
        <span className="text-[10px] text-gray-600">{tc.tool_type}</span>
        {tc.duration_ms !== null && <span className="text-[10px] text-gray-600">{tc.duration_ms}ms</span>}
      </div>
      {tc.created_at && <p className="text-[10px] text-gray-600 mt-0.5">{new Date(tc.created_at).toLocaleString()}</p>}
      {expanded && (
        <div className="mt-2 pt-2 border-t border-surface-3 space-y-2">
          <div>
            <span className="text-[10px] text-gray-500 block mb-0.5">Arguments</span>
            <pre className="text-[10px] text-gray-400 font-mono whitespace-pre-wrap bg-surface-0 rounded p-2 overflow-x-auto">
              {JSON.stringify(tc.arguments, null, 2)}
            </pre>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block mb-0.5">Result</span>
            <pre className="text-[10px] text-gray-400 font-mono whitespace-pre-wrap bg-surface-0 rounded p-2 overflow-x-auto max-h-48 overflow-y-auto">
              {tc.result}
            </pre>
          </div>
          {tc.error && (
            <div>
              <span className="text-[10px] text-red-400 block mb-0.5">Error</span>
              <pre className="text-[10px] text-red-300 font-mono whitespace-pre-wrap bg-surface-0 rounded p-2">
                {tc.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function TraceRow({ te }: { te: ChannelContext["trace_events"][0] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className="rounded-lg border border-surface-3 p-3 cursor-pointer hover:bg-surface-1 transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-gray-200">{te.event_type}</span>
        {te.event_name && <span className="text-[10px] text-gray-500">{te.event_name}</span>}
        {te.duration_ms !== null && <span className="text-[10px] text-gray-600">{te.duration_ms}ms</span>}
      </div>
      {te.created_at && <p className="text-[10px] text-gray-600 mt-0.5">{new Date(te.created_at).toLocaleString()}</p>}
      {expanded && te.data && (
        <div className="mt-2 pt-2 border-t border-surface-3">
          <pre className="text-[10px] text-gray-400 font-mono whitespace-pre-wrap bg-surface-0 rounded p-2 overflow-x-auto">
            {JSON.stringify(te.data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
