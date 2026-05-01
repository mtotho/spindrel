import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Bot, Check, Eye, FileText, History, MessageSquare, PenLine, Save, Sparkles, Tags, X } from "lucide-react";
import {
  useAssistChannelNote,
  useChannel,
  useChannelNote,
  useChannelWorkspaceFileVersions,
  useWriteChannelNote,
  type ChannelNoteAssistProposal,
} from "@/src/api/hooks/useChannels";
import { SourceTextEditor } from "@/src/components/shared/SourceTextEditor";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
import { ChatSession } from "@/src/components/chat/ChatSession";

type SelectionState = { start: number; end: number; text: string };

export default function NoteWorkspacePage() {
  const { channelId, slug } = useParams<{ channelId: string; slug: string }>();
  const navigate = useNavigate();
  const channelQuery = useChannel(channelId);
  const noteQuery = useChannelNote(channelId, slug ?? null);
  const writeNote = useWriteChannelNote(channelId ?? "");
  const assistNote = useAssistChannelNote(channelId ?? "");
  const note = noteQuery.data ?? null;
  const versionsQuery = useChannelWorkspaceFileVersions(channelId, note?.path ?? null, !!note);

  const [bodyDraft, setBodyDraft] = useState("");
  const [frontmatter, setFrontmatter] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [baseHash, setBaseHash] = useState<string | null>(null);
  const [selection, setSelection] = useState<SelectionState>({ start: 0, end: 0, text: "" });
  const [preview, setPreview] = useState(false);
  const [proposal, setProposal] = useState<ChannelNoteAssistProposal | null>(null);
  const [customInstruction, setCustomInstruction] = useState("");
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    if (!note) return;
    const split = splitFrontmatter(note.content);
    setFrontmatter(split.frontmatter);
    setBodyDraft(split.body);
    setTitleDraft(note.title);
    setBaseHash(note.content_hash);
    setProposal(null);
    setSelection({ start: 0, end: 0, text: "" });
  }, [note]);

  const fullDraft = useMemo(
    () => `${setFrontmatterField(frontmatter, "title", titleDraft.trim() || "Untitled")}${bodyDraft}`,
    [bodyDraft, frontmatter, titleDraft],
  );
  const dirty = Boolean(note && fullDraft !== note.content);
  const selectedText = selection.text.trim();

  const handleSave = useCallback(async () => {
    if (!channelId || !slug) return;
    const saved = await writeNote.mutateAsync({ slug, content: fullDraft, base_hash: baseHash });
    const split = splitFrontmatter(saved.content);
    setFrontmatter(split.frontmatter);
    setBodyDraft(split.body);
    setBaseHash(saved.content_hash);
    setProposal(null);
  }, [baseHash, channelId, fullDraft, slug, writeNote]);

  const handleAssist = useCallback(async (mode: string) => {
    if (!slug) return;
    const proposal = await assistNote.mutateAsync({
      slug,
      mode,
      instruction: mode === "custom" ? customInstruction : undefined,
      selection: selectedText ? selection : null,
      base_hash: baseHash,
    });
    setProposal(proposal);
  }, [assistNote, baseHash, customInstruction, selectedText, selection, slug]);

  const acceptProposal = useCallback(() => {
    if (!proposal) return;
    if (proposal.target === "selection" && selectedText) {
      setBodyDraft((current) => current.slice(0, selection.start) + proposal.replacement_markdown + current.slice(selection.end));
    } else {
      setBodyDraft(stripFrontmatter(proposal.replacement_markdown));
    }
    setProposal(null);
  }, [proposal, selectedText, selection.end, selection.start]);

  if (!channelId || !slug) {
    return <div className="p-6 text-text-muted">Missing note route.</div>;
  }

  if (noteQuery.isLoading) {
    return <div className="flex h-full items-center justify-center text-sm text-text-dim">Loading note...</div>;
  }

  if (!note) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="rounded-md border border-dashed border-surface-border bg-surface-raised/40 px-6 py-8 text-center text-sm text-text-muted">
          Note not found.
        </div>
      </div>
    );
  }

  const channelName = channelQuery.data?.display_name || channelQuery.data?.name || "Channel";
  const botId = channelQuery.data?.bot_id;

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="flex min-h-0 flex-1 flex-col px-4 py-3 sm:px-6 lg:px-8">
        <header className="flex shrink-0 items-center gap-3 pb-3">
          <button
            type="button"
            onClick={() => navigate(`/channels/${encodeURIComponent(channelId)}`)}
            className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay hover:text-text"
            aria-label="Back to channel"
          >
            <ArrowLeft size={17} />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <FileText size={16} className="shrink-0 text-emphasis" />
              <input
                value={titleDraft}
                onChange={(event) => setTitleDraft(event.target.value)}
                className="min-w-0 flex-1 bg-transparent text-[18px] font-semibold text-text outline-none placeholder:text-text-dim"
                placeholder="Untitled"
              />
              <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim">
                {note.scope}
              </span>
            </div>
            <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-2 text-[11px] text-text-dim">
              <span>{channelName}</span>
              <span>{note.word_count} words</span>
              <span>{versionsQuery.data?.versions.length ?? 0} revisions</span>
              <Link to={`/channels/${encodeURIComponent(channelId)}`} className="text-accent hover:underline">Channel</Link>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setPreview((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] text-text-muted hover:bg-surface-overlay"
          >
            {preview ? <PenLine size={14} /> : <Eye size={14} />}
            {preview ? "Edit" : "Preview"}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty || writeNote.isPending}
            className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] text-accent hover:bg-surface-overlay disabled:opacity-40"
          >
            <Save size={14} />
            Save
          </button>
        </header>

        <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_340px]">
          <section className="min-h-0 rounded-md bg-surface-raised/55 p-2">
            {preview ? (
              <div className="h-full min-h-[560px] overflow-auto rounded-md bg-surface px-4 py-4">
                <MarkdownViewer content={bodyDraft} />
              </div>
            ) : (
              <SourceTextEditor
                value={bodyDraft}
                language="markdown"
                onChange={setBodyDraft}
                onSelectionChange={setSelection}
                minHeight={560}
                maxHeight={undefined}
                className="h-full"
                status={{ variant: dirty ? "neutral" : "success", label: dirty ? "Unsaved Markdown note" : "Saved Markdown note" }}
              />
            )}
          </section>

          <aside className="flex min-h-0 flex-col gap-3 rounded-md bg-surface-raised/55 p-3">
            <section className="flex shrink-0 flex-col gap-2">
              <div className="flex items-center gap-1.5 text-[12px] font-medium text-text">
                <Bot size={14} className="text-emphasis" />
                Note assistant
              </div>
              <div className="text-[11px] text-text-dim">
                {selectedText ? `${selectedText.length} selected characters` : "Whole note target"}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {note.category && <span className="rounded-full bg-surface-overlay px-2 py-0.5 text-[11px] text-text-muted">{note.category}</span>}
                {note.tags.map((tag) => (
                  <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-surface-overlay px-2 py-0.5 text-[11px] text-text-muted">
                    <Tags size={10} />
                    {tag}
                  </span>
                ))}
              </div>
            </section>

            <section className="flex shrink-0 flex-col gap-2">
              <button
                type="button"
                onClick={() => void handleAssist("clarify_structure")}
                disabled={assistNote.isPending}
                className="inline-flex items-center justify-center gap-1.5 rounded-md bg-accent/[0.10] px-3 py-2 text-[12px] font-medium text-accent hover:bg-accent/[0.16] disabled:opacity-40"
              >
                <Sparkles size={14} />
                Clarify & Structure
              </button>
              <textarea
                value={customInstruction}
                onChange={(event) => setCustomInstruction(event.target.value)}
                placeholder="Ask for a specific change"
                className="min-h-[76px] resize-none rounded-md bg-input px-2.5 py-2 text-[12px] text-text outline-none placeholder:text-text-dim"
              />
              <button
                type="button"
                onClick={() => void handleAssist("custom")}
                disabled={!customInstruction.trim() || assistNote.isPending}
                className="rounded-md px-3 py-2 text-[12px] text-text-muted hover:bg-surface-overlay disabled:opacity-40"
              >
                Propose change
              </button>
              <button
                type="button"
                onClick={() => setChatOpen(true)}
                className="inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-[12px] text-text-muted hover:bg-surface-overlay"
              >
                <MessageSquare size={14} />
                Open note chat
              </button>
            </section>

            <section className="flex min-h-0 flex-1 flex-col gap-2">
              {proposal ? (
                <>
                  <div className="text-[12px] text-text-muted">{proposal.rationale}</div>
                  <pre className="min-h-[180px] flex-1 overflow-auto whitespace-pre-wrap rounded-md bg-input p-2 text-[11px] text-text">
                    {proposal.diff || proposal.replacement_markdown}
                  </pre>
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
                </>
              ) : (
                <div className="flex flex-1 items-center gap-2 rounded-md border border-dashed border-surface-border px-3 py-4 text-[12px] text-text-dim">
                  <History size={14} />
                  Revisions are created before each overwrite.
                </div>
              )}
            </section>
          </aside>
        </main>
      </div>

      {note.session_id && botId && (
        <ChatSession
          source={{
            kind: "ephemeral",
            sessionStorageKey: `note:${channelId}:${note.slug}`,
            parentChannelId: channelId,
            defaultBotId: botId,
            pinnedSessionId: note.session_id,
            context: {
              page_name: `Notes: ${note.title}`,
              tags: ["notes", "markdown", "knowledge-base"],
              tool_hints: ["workspace/notes", "workspace/knowledge_bases", "grill_me"],
              payload: { note_path: note.path, note_title: note.title },
            },
          }}
          shape="dock"
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          title={`Note: ${note.title}`}
          dockCollapsedTitle="Note assistant"
          dockCollapsedSubtitle={note.title}
          dismissMode="close"
          chatMode="terminal"
          initiallyExpanded
        />
      )}
    </div>
  );
}

function splitFrontmatter(content: string): { frontmatter: string; body: string } {
  if (!content.startsWith("---\n")) return { frontmatter: "", body: content };
  const end = content.indexOf("\n---", 4);
  if (end < 0) return { frontmatter: "", body: content };
  let bodyStart = end + "\n---".length;
  while (content[bodyStart] === "\n" || content[bodyStart] === "\r") bodyStart += 1;
  return { frontmatter: content.slice(0, bodyStart), body: content.slice(bodyStart) };
}

function stripFrontmatter(content: string): string {
  return splitFrontmatter(content).body;
}

function setFrontmatterField(frontmatter: string, key: string, value: string): string {
  const safeValue = yamlScalar(value);
  if (!frontmatter.trim()) {
    return `---\nspindrel_kind: note\n${key}: ${safeValue}\ntags: []\n---\n\n`;
  }
  const lines = frontmatter.replace(/\s+$/g, "").split("\n");
  const field = `${key}: ${safeValue}`;
  const index = lines.findIndex((line) => line.startsWith(`${key}:`));
  if (index >= 0) {
    lines[index] = field;
  } else {
    const end = lines.lastIndexOf("---");
    lines.splice(end > 0 ? end : lines.length, 0, field);
  }
  return `${lines.join("\n")}\n\n`;
}

function yamlScalar(value: string): string {
  if (!value || /[:#\[\]{}\n\r]|^\s|\s$/.test(value)) {
    return JSON.stringify(value);
  }
  return value;
}
