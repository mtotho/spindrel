import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Check, FileText, History, ListFilter, MessageSquare, PenLine, Plus, Sparkles, Tags, X } from "lucide-react";
import {
  useAssistChannelNote,
  useChannelNote,
  useChannelNotes,
  useChannelWorkspaceFileVersions,
  useCreateChannelNote,
  useWriteChannelNote,
  type ChannelNoteAssistProposal,
  type ChannelNoteSummary,
} from "@/src/api/hooks/useChannels";
import { SourceTextEditor } from "@/src/components/shared/SourceTextEditor";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
import { ChatSession } from "@/src/components/chat/ChatSession";

interface NotesTabPanelProps {
  channelId: string;
  botId: string | undefined;
  onSelectFile?: (path: string, options?: { split?: boolean }) => void;
}

type SelectionState = { start: number; end: number; text: string };

export function NotesTabPanel({ channelId, botId, onSelectFile }: NotesTabPanelProps) {
  const notesQuery = useChannelNotes(channelId);
  const createNote = useCreateChannelNote(channelId);
  const writeNote = useWriteChannelNote(channelId);
  const assistNote = useAssistChannelNote(channelId);
  const [query, setQuery] = useState("");
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [baseHash, setBaseHash] = useState<string | null>(null);
  const [selection, setSelection] = useState<SelectionState>({ start: 0, end: 0, text: "" });
  const [preview, setPreview] = useState(false);
  const [proposal, setProposal] = useState<ChannelNoteAssistProposal | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [customInstruction, setCustomInstruction] = useState("");

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

  useEffect(() => {
    if (!activeSlug && notes[0]) setActiveSlug(notes[0].slug);
  }, [activeSlug, notes]);

  const activeNoteQuery = useChannelNote(channelId, activeSlug);
  const activeNote = activeNoteQuery.data ?? null;
  const versionsQuery = useChannelWorkspaceFileVersions(channelId, activeNote?.path ?? null, !!activeNote);

  useEffect(() => {
    if (!activeNote) return;
    setDraft(activeNote.content);
    setBaseHash(activeNote.content_hash);
    setProposal(null);
    setSelection({ start: 0, end: 0, text: "" });
  }, [activeNote]);

  const dirty = Boolean(activeNote && draft !== activeNote.content);
  const selectedText = selection.text.trim();
  const previewBody = stripFrontmatter(draft);

  const handleCreate = useCallback(async () => {
    const title = window.prompt("New note title");
    if (!title?.trim()) return;
    const note = await createNote.mutateAsync({ title: title.trim() });
    setActiveSlug(note.slug);
  }, [createNote]);

  const handleSave = useCallback(async () => {
    if (!activeSlug) return;
    const saved = await writeNote.mutateAsync({ slug: activeSlug, content: draft, base_hash: baseHash });
    setDraft(saved.content);
    setBaseHash(saved.content_hash);
    setProposal(null);
  }, [activeSlug, baseHash, draft, writeNote]);

  const handleAssist = useCallback(async (mode: string) => {
    if (!activeSlug) return;
    const proposal = await assistNote.mutateAsync({
      slug: activeSlug,
      mode,
      instruction: mode === "custom" ? customInstruction : undefined,
      selection: selectedText ? selection : null,
      base_hash: baseHash,
    });
    setProposal(proposal);
  }, [activeSlug, assistNote, baseHash, customInstruction, selectedText, selection]);

  const acceptProposal = useCallback(() => {
    if (!proposal) return;
    if (proposal.target === "selection" && selectedText) {
      setDraft((current) => current.slice(0, selection.start) + proposal.replacement_markdown + current.slice(selection.end));
    } else {
      setDraft(proposal.replacement_markdown);
    }
    setProposal(null);
  }, [proposal, selectedText, selection.end, selection.start]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <FileText size={15} className="text-emphasis" />
          <div className="min-w-0">
            <div className="truncate text-[13px] font-medium text-text">Notes</div>
            <div className="truncate text-[11px] text-text-dim">
              {notesQuery.data?.surface.scope === "project" ? "Project knowledge" : "Channel knowledge"}
            </div>
          </div>
        </div>
        <button type="button" onClick={handleCreate} className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-[12px] text-accent hover:bg-surface-overlay">
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

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-3 pb-3">
        <div className="flex shrink-0 gap-2 overflow-x-auto pb-1">
          {filtered.map((note) => (
            <NoteRow key={note.slug} note={note} active={note.slug === activeSlug} onClick={() => setActiveSlug(note.slug)} />
          ))}
          {!notesQuery.isLoading && filtered.length === 0 && (
            <div className="w-full rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-3 py-8 text-center text-[12px] text-text-dim">
              No notes match this filter.
            </div>
          )}
        </div>

        <div className="min-h-[520px] flex-1 rounded-md bg-surface-raised/55 p-2">
          {!activeNote ? (
            <div className="flex h-full min-h-[320px] items-center justify-center text-[12px] text-text-dim">
              {notesQuery.isLoading ? "Loading notes..." : "Create a note to start."}
            </div>
          ) : (
            <div className="flex h-full min-h-0 flex-col gap-2">
              <div className="flex items-center gap-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium text-text">{activeNote.title}</div>
                  <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-text-dim">
                    <span>{activeNote.word_count} words</span>
                    <span>{versionsQuery.data?.versions.length ?? 0} revisions</span>
                    {activeNote.category && <span>{activeNote.category}</span>}
                  </div>
                </div>
                {onSelectFile && (
                  <button type="button" onClick={() => onSelectFile(activeNote.path)} className="rounded-md p-1.5 text-text-muted hover:bg-surface-overlay" title="Open in Files">
                    <PenLine size={14} />
                  </button>
                )}
                <button type="button" onClick={() => setPreview((v) => !v)} className="rounded-md px-2 py-1.5 text-[12px] text-text-muted hover:bg-surface-overlay">
                  {preview ? "Edit" : "Preview"}
                </button>
                <button type="button" onClick={handleSave} disabled={!dirty || writeNote.isPending} className="rounded-md px-2 py-1.5 text-[12px] text-accent hover:bg-surface-overlay disabled:opacity-40">
                  Save
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                <button type="button" onClick={() => void handleAssist("clarify_structure")} disabled={assistNote.isPending} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[12px] text-accent hover:bg-surface-overlay disabled:opacity-40">
                  <Sparkles size={13} />
                  Clarify & Structure
                </button>
                <input
                  value={customInstruction}
                  onChange={(event) => setCustomInstruction(event.target.value)}
                  placeholder="Custom change"
                  className="min-w-[140px] flex-1 rounded-md bg-input px-2 py-1.5 text-[12px] text-text outline-none"
                />
                <button type="button" onClick={() => void handleAssist("custom")} disabled={!customInstruction.trim() || assistNote.isPending} className="rounded-md px-2 py-1.5 text-[12px] text-text-muted hover:bg-surface-overlay disabled:opacity-40">
                  Propose
                </button>
                <button type="button" onClick={() => setChatOpen(true)} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[12px] text-text-muted hover:bg-surface-overlay">
                  <MessageSquare size={13} />
                  Chat
                </button>
              </div>

              <div className="flex min-h-0 flex-1 flex-col gap-2 xl:flex-row">
                <div className="min-h-0 flex-1">
                  {preview ? (
                    <div className="h-full min-h-[360px] overflow-auto rounded-md bg-surface px-2 py-2">
                      <MarkdownViewer content={previewBody} />
                    </div>
                  ) : (
                    <SourceTextEditor
                      value={draft}
                      language="markdown"
                      onChange={setDraft}
                      onSelectionChange={setSelection}
                      minHeight={360}
                      maxHeight={700}
                      className="h-full"
                      status={{ variant: dirty ? "neutral" : "success", label: dirty ? "Unsaved Markdown" : "Saved Markdown" }}
                    />
                  )}
                </div>

                <div className="flex min-h-[180px] flex-col gap-2 rounded-md bg-surface-overlay/30 p-2 xl:w-[300px]">
                  <div className="flex items-center gap-1.5 text-[12px] font-medium text-text">
                    <Bot size={14} className="text-emphasis" />
                    Note assistant
                  </div>
                  <div className="text-[11px] text-text-dim">
                    {selectedText ? `${selectedText.length} selected chars` : "Whole document target"}
                  </div>
                  {activeNote.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {activeNote.tags.map((tag) => (
                        <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-surface-overlay px-2 py-0.5 text-[11px] text-text-muted">
                          <Tags size={10} />
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                  {proposal ? (
                    <div className="flex min-h-0 flex-1 flex-col gap-2">
                      <div className="text-[12px] text-text-muted">{proposal.rationale}</div>
                      <pre className="min-h-[90px] flex-1 overflow-auto whitespace-pre-wrap rounded-md bg-input p-2 text-[11px] text-text">{proposal.diff || proposal.replacement_markdown}</pre>
                      <div className="flex gap-2">
                        <button type="button" onClick={acceptProposal} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[12px] text-accent hover:bg-surface-overlay">
                          <Check size={13} />
                          Accept
                        </button>
                        <button type="button" onClick={() => setProposal(null)} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[12px] text-text-muted hover:bg-surface-overlay">
                          <X size={13} />
                          Reject
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-1 items-center gap-2 rounded-md border border-dashed border-surface-border px-3 py-4 text-[12px] text-text-dim">
                      <History size={14} />
                      Revisions are created on every overwrite.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {activeNote?.session_id && botId && (
        <ChatSession
          source={{
            kind: "ephemeral",
            sessionStorageKey: `note:${channelId}:${activeNote.slug}`,
            parentChannelId: channelId,
            defaultBotId: botId,
            pinnedSessionId: activeNote.session_id,
            context: {
              page_name: `Notes: ${activeNote.title}`,
              tags: ["notes", "markdown", "knowledge-base"],
              tool_hints: ["workspace/notes", "workspace/knowledge_bases", "grill_me"],
              payload: { note_path: activeNote.path, note_title: activeNote.title },
            },
          }}
          shape="dock"
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          title={`Note: ${activeNote.title}`}
          dockCollapsedTitle="Note assistant"
          dockCollapsedSubtitle={activeNote.title}
          dismissMode="close"
          chatMode="terminal"
          initiallyExpanded
        />
      )}
    </div>
  );
}

function NoteRow({ note, active, onClick }: { note: ChannelNoteSummary; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-w-[220px] max-w-[260px] rounded-md px-3 py-2 text-left transition-colors ${
        active ? "bg-accent/[0.10]" : "bg-surface-raised hover:bg-surface-overlay/50"
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">{note.title}</span>
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim">{note.scope}</span>
      </div>
      <div className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-text-muted">
        {note.summary || note.excerpt || "Empty note"}
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-[10px] text-text-dim">
        <span>{note.word_count} words</span>
        {note.tags.slice(0, 2).map((tag) => <span key={tag}>#{tag}</span>)}
      </div>
    </button>
  );
}

function stripFrontmatter(content: string) {
  if (!content.startsWith("---\n")) return content;
  const end = content.indexOf("\n---", 4);
  if (end < 0) return content;
  let bodyStart = end + "\n---".length;
  if (content[bodyStart] === "\n") bodyStart += 1;
  return content.slice(bodyStart);
}
