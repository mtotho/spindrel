import { useCallback, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileText, ListFilter, NotebookText, Plus, Tags } from "lucide-react";
import {
  useChannelNotes,
  useCreateChannelNote,
  type ChannelNoteSummary,
} from "@/src/api/hooks/useChannels";

interface NotesTabPanelProps {
  channelId: string;
  botId: string | undefined;
  onSelectFile?: (path: string, options?: { split?: boolean }) => void;
}

export function NotesTabPanel({ channelId }: NotesTabPanelProps) {
  const navigate = useNavigate();
  const notesQuery = useChannelNotes(channelId);
  const createNote = useCreateChannelNote(channelId);
  const [query, setQuery] = useState("");

  const notes = notesQuery.data?.notes ?? [];
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return notes;
    return notes.filter((note) => [
      note.title,
      note.summary,
      note.excerpt,
      note.category,
      note.tags.join(" "),
    ].join(" ").toLowerCase().includes(needle));
  }, [notes, query]);

  const openNote = useCallback((slug: string) => {
    navigate(`/channels/${encodeURIComponent(channelId)}/notes/${encodeURIComponent(slug)}`);
  }, [channelId, navigate]);

  const handleCreate = useCallback(async () => {
    const note = await createNote.mutateAsync({
      title: "Untitled",
      content: "# Untitled\n\n",
    });
    openNote(note.slug);
  }, [createNote, openNote]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <NotebookText size={15} className="text-emphasis" />
          <div className="min-w-0">
            <div className="truncate text-[13px] font-medium text-text">Notes</div>
            <div className="truncate text-[11px] text-text-dim">
              {notesQuery.data?.surface.scope === "project" ? "Project knowledge" : "Channel knowledge"}
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={handleCreate}
          disabled={createNote.isPending}
          className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[12px] text-accent hover:bg-surface-overlay disabled:opacity-40"
        >
          <Plus size={14} />
          New
        </button>
      </div>

      <div className="px-3 pb-2">
        <div className="flex items-center gap-2 rounded-md bg-input px-2 py-1.5 text-text-muted">
          <ListFilter size={13} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter notes"
            className="min-w-0 flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        <div className="flex flex-col gap-2">
          {filtered.map((note) => (
            <NoteListItem key={note.slug} note={note} onClick={() => openNote(note.slug)} />
          ))}
          {!notesQuery.isLoading && filtered.length === 0 && (
            <div className="mx-1 rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-4 py-8 text-center">
              <FileText size={18} className="mx-auto mb-2 text-text-dim/70" />
              <div className="text-[12px] text-text-muted">No notes yet</div>
              <button
                type="button"
                onClick={handleCreate}
                disabled={createNote.isPending}
                className="mt-3 inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-[12px] text-accent hover:bg-surface-overlay disabled:opacity-40"
              >
                <Plus size={13} />
                Start an untitled note
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NoteListItem({ note, onClick }: { note: ChannelNoteSummary; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mx-1 rounded-md bg-surface-raised/70 px-3 py-2.5 text-left transition-colors hover:bg-surface-overlay/55"
    >
      <div className="flex items-start gap-2">
        <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-emphasis/10 text-emphasis">
          <NotebookText size={13} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">{note.title}</span>
            <span className="shrink-0 rounded-full bg-surface-overlay px-1.5 py-0.5 text-[9px] uppercase tracking-[0.08em] text-text-dim">
              {note.scope}
            </span>
          </div>
          <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-text-muted">
            {note.summary || note.excerpt || "Untitled working note"}
          </div>
          <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5 text-[10px] text-text-dim">
            <span>{note.word_count} words</span>
            {note.category && <span>{note.category}</span>}
            {note.tags.slice(0, 2).map((tag) => (
              <span key={tag} className="inline-flex items-center gap-0.5">
                <Tags size={9} />
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>
    </button>
  );
}
