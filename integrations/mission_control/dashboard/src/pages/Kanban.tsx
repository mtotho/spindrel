/**
 * Full-page kanban view for a channel.
 * Uses the same KanbanBoard component as the channel detail tab,
 * but with more screen space.
 */

import { useParams, Link } from "react-router-dom";
import { useKanban } from "../hooks/useKanban";
import { useOverview } from "../hooks/useOverview";
import KanbanBoard from "../components/KanbanBoard";
import EmptyState from "../components/EmptyState";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import { generateCardId } from "../lib/parser";
import type { KanbanColumn } from "../lib/types";

export default function Kanban() {
  const { channelId } = useParams<{ channelId: string }>();
  const { data: columns, isLoading, error, saveColumns, isSaving } = useKanban(channelId);
  const { data: overview } = useOverview();
  const channel = overview?.channels.find((ch) => ch.id === channelId);

  if (isLoading) return <LoadingSpinner />;
  if (error) {
    if (error.message.includes("404")) {
      return (
        <div className="p-6">
          <EmptyState
            icon="▦"
            title="No kanban board yet"
            description="This channel doesn't have a tasks.md file. Ask your bot to create one, or use the create_task_card tool."
          />
        </div>
      );
    }
    return <div className="p-6"><ErrorBanner message={error.message} /></div>;
  }
  if (!columns) return null;

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
      meta: {
        id: generateCardId(),
        priority: card.priority,
        created: today,
      },
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

  return (
    <div className="p-6 h-screen flex flex-col">
      <div className="mb-4 flex items-center gap-3">
        <Link
          to={`/channels/${channelId}`}
          className="text-xs text-gray-500 hover:text-gray-400 transition-colors"
        >
          &larr; Channel
        </Link>
        <h1 className="text-lg font-bold text-gray-100" title={channelId}>
          {channel?.name || channelId?.slice(0, 8)} — Kanban
        </h1>
      </div>
      <div className="flex-1 overflow-hidden">
        <KanbanBoard columns={columns} onMove={handleMove} onAddCard={handleAddCard} isSaving={isSaving} />
      </div>
    </div>
  );
}
