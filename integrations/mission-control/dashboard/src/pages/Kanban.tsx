/**
 * Full-page kanban view for a channel.
 * Uses the same KanbanBoard component as the channel detail tab,
 * but with more screen space.
 */

import { useParams, Link } from "react-router-dom";
import { useKanban } from "../hooks/useKanban";
import { useOverview } from "../hooks/useOverview";
import KanbanBoard from "../components/KanbanBoard";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import type { KanbanColumn } from "../lib/types";

export default function Kanban() {
  const { channelId } = useParams<{ channelId: string }>();
  const { data: columns, isLoading, error, saveColumns, isSaving } = useKanban(channelId);
  const { data: overview } = useOverview();
  const channel = overview?.channels.find((ch) => ch.id === channelId);

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

  return (
    <div className="p-6 h-screen flex flex-col">
      <div className="mb-4 flex items-center gap-3">
        <Link
          to={`/channels/${channelId}`}
          className="text-xs text-gray-500 hover:text-gray-400 transition-colors"
        >
          &larr; Channel
        </Link>
        <h1 className="text-lg font-bold text-gray-100">
          {channel?.name || channelId?.slice(0, 8)} — Kanban
        </h1>
      </div>
      <div className="flex-1 overflow-hidden">
        <KanbanBoard columns={columns} onMove={handleMove} isSaving={isSaving} />
      </div>
    </div>
  );
}
