import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  Eye,
  FileText,
  MessageSquare,
  PenLine,
  Save,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import {
  useAssistChannelNote,
  useChannel,
  useChannelNote,
  useChannelWorkspaceFileVersions,
  useWriteChannelNote,
  type ChannelNoteAssistProposal,
} from "@/src/api/hooks/useChannels";
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
  const [aiFlash, setAiFlash] = useState(false);

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
  const proposalMeaningful = proposal ? normalizeMd(proposal.replacement_markdown) !== normalizeMd(proposal.target === "selection" && selectedText ? selectedText : bodyDraft) : false;

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
    const next = await assistNote.mutateAsync({
      slug,
      mode,
      instruction: mode === "custom" ? customInstruction : undefined,
      selection: selectedText ? selection : null,
      base_hash: baseHash,
    });
    setProposal(next);
    setAiFlash(true);
    window.setTimeout(() => setAiFlash(false), 900);
  }, [assistNote, baseHash, customInstruction, selectedText, selection, slug]);

  const acceptProposal = useCallback(() => {
    if (!proposal) return;
    if (!proposalMeaningful) {
      setProposal(null);
      return;
    }
    if (proposal.target === "selection" && selectedText) {
      setBodyDraft((current) => current.slice(0, selection.start) + proposal.replacement_markdown + current.slice(selection.end));
    } else {
      setBodyDraft(stripFrontmatter(proposal.replacement_markdown));
    }
    setProposal(null);
    setAiFlash(true);
    window.setTimeout(() => setAiFlash(false), 900);
  }, [proposal, proposalMeaningful, selectedText, selection.end, selection.start]);

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
  const targetLabel = selectedText ? `${selectedText.length} selected chars` : "Whole note";

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <header className="flex h-12 shrink-0 items-center gap-3 px-4 sm:px-6 lg:px-8">
        <button
          type="button"
          onClick={() => navigate(`/channels/${encodeURIComponent(channelId)}`)}
          className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted hover:bg-surface-overlay hover:text-text"
          aria-label="Back to channel"
        >
          <ArrowLeft size={17} />
        </button>
        <FileText size={16} className="shrink-0 text-emphasis" />
        <input
          value={titleDraft}
          onChange={(event) => setTitleDraft(event.target.value)}
          className="min-w-0 flex-1 bg-transparent text-[18px] font-semibold text-text outline-none placeholder:text-text-dim"
          placeholder="Untitled"
        />
        <span className="hidden rounded-full bg-surface-overlay px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim sm:inline-flex">
          {note.scope}
        </span>
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

      <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pb-2 text-[11px] text-text-dim sm:px-6 lg:px-8">
        <span>{channelName}</span>
        <span>{wordCount(bodyDraft)} words</span>
        <span>{versionsQuery.data?.versions.length ?? 0} revisions</span>
        <span>{targetLabel}</span>
        <Link to={`/channels/${encodeURIComponent(channelId)}`} className="text-accent hover:underline">Channel</Link>
      </div>

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-3 px-4 pb-4 sm:px-6 lg:px-8 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className={`relative min-h-0 overflow-hidden rounded-md bg-surface-raised/45 ${aiFlash ? "note-ai-flash" : ""}`}>
          {preview ? (
            <div className="h-full overflow-auto bg-surface px-8 py-7">
              <MarkdownViewer content={bodyDraft} />
            </div>
          ) : (
            <MarkdownNoteEditor value={bodyDraft} onChange={setBodyDraft} onSelectionChange={setSelection} />
          )}
          {assistNote.isPending && (
            <div className="pointer-events-none absolute inset-x-6 top-6 flex items-center gap-2 rounded-md bg-accent/[0.10] px-3 py-2 text-[12px] text-accent">
              <Sparkles size={14} className="thinking-pulse" />
              Authoring a Markdown proposal...
            </div>
          )}
        </section>

        <aside className="flex min-h-0 flex-col gap-3 rounded-md bg-surface-raised/55 p-3">
          <div className="flex shrink-0 items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-emphasis/10 text-emphasis">
              <Wand2 size={15} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[12px] font-medium text-text">Magic edit</div>
              <div className="text-[11px] text-text-dim">{targetLabel}</div>
            </div>
          </div>

          <button
            type="button"
            onClick={() => void handleAssist("clarify_structure")}
            disabled={assistNote.isPending}
            className="inline-flex items-center justify-center gap-1.5 rounded-md bg-accent/[0.10] px-3 py-2 text-[12px] font-medium text-accent hover:bg-accent/[0.16] disabled:opacity-40"
          >
            <Sparkles size={14} />
            Clarify & Structure
          </button>

          <div className="flex shrink-0 flex-col gap-2 rounded-md bg-input p-2">
            <textarea
              value={customInstruction}
              onChange={(event) => setCustomInstruction(event.target.value)}
              placeholder="Tell the assistant what to change"
              className="min-h-[84px] resize-none bg-transparent text-[13px] leading-relaxed text-text outline-none placeholder:text-text-dim"
            />
            <button
              type="button"
              onClick={() => void handleAssist("custom")}
              disabled={!customInstruction.trim() || assistNote.isPending}
              className="self-end rounded-md px-2.5 py-1.5 text-[12px] text-accent hover:bg-surface-overlay disabled:opacity-40"
            >
              Propose
            </button>
          </div>

          <button
            type="button"
            onClick={() => setChatOpen(true)}
            className="inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-[12px] text-text-muted hover:bg-surface-overlay"
          >
            <MessageSquare size={14} />
            Open note chat
          </button>

          <div className="min-h-0 flex-1 overflow-hidden">
            {proposal ? (
              <ProposalReview
                proposal={proposal}
                meaningful={proposalMeaningful}
                onAccept={acceptProposal}
                onReject={() => setProposal(null)}
              />
            ) : (
              <div className="flex h-full items-center rounded-md border border-dashed border-surface-border px-3 py-4 text-[12px] leading-relaxed text-text-dim">
                Highlight text or write an instruction, then let the assistant prepare a reviewable Markdown draft.
              </div>
            )}
          </div>
        </aside>
      </main>

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

function MarkdownNoteEditor({
  value,
  onChange,
  onSelectionChange,
}: {
  value: string;
  onChange: (value: string) => void;
  onSelectionChange: (selection: SelectionState) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const emitSelection = useCallback((target: HTMLTextAreaElement) => {
    onSelectionChange({
      start: target.selectionStart,
      end: target.selectionEnd,
      text: target.value.slice(target.selectionStart, target.selectionEnd),
    });
  }, [onSelectionChange]);

  const commit = useCallback((next: string, start: number, end = start) => {
    onChange(next);
    window.requestAnimationFrame(() => {
      const target = textareaRef.current;
      if (!target) return;
      target.focus();
      target.selectionStart = start;
      target.selectionEnd = end;
      emitSelection(target);
    });
  }, [emitSelection, onChange]);

  const replaceSelection = useCallback((replacement: string, selectOffset = replacement.length) => {
    const target = textareaRef.current;
    if (!target) return;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const next = value.slice(0, start) + replacement + value.slice(end);
    commit(next, start + selectOffset);
  }, [commit, value]);

  const transformSelectedLines = useCallback((transform: (line: string, index: number) => string) => {
    const target = textareaRef.current;
    if (!target) return;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const lineStart = value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    const trailingNewlineSelected = end > start && value[end - 1] === "\n";
    const effectiveEnd = trailingNewlineSelected ? end - 1 : end;
    const nextBreak = value.indexOf("\n", effectiveEnd);
    const lineEnd = nextBreak === -1 ? value.length : nextBreak;
    const block = value.slice(lineStart, lineEnd);
    const lines = block.split("\n");
    const transformed = lines.map(transform).join("\n");
    const next = value.slice(0, lineStart) + transformed + value.slice(lineEnd);
    const mapOffset = (offset: number) => {
      const prefix = block.slice(0, Math.max(0, Math.min(offset, block.length)));
      return prefix.split("\n").map(transform).join("\n").length;
    };
    const nextStart = lineStart + mapOffset(start - lineStart);
    const nextEnd = lineStart + mapOffset(Math.min(end, lineEnd) - lineStart) + Math.max(0, end - lineEnd);
    commit(next, nextStart, nextEnd);
  }, [commit, value]);

  const indentLines = useCallback((outdent: boolean) => {
    transformSelectedLines((line) => {
      if (!outdent) return `  ${line}`;
      if (line.startsWith("  ")) return line.slice(2);
      if (line.startsWith("\t")) return line.slice(1);
      if (line.startsWith(" ")) return line.slice(1);
      return line;
    });
  }, [transformSelectedLines]);

  const continueMarkdownLine = useCallback(() => {
    const target = textareaRef.current;
    if (!target) return false;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    if (start !== end) return false;
    const lineStart = value.lastIndexOf("\n", Math.max(0, start - 1)) + 1;
    const line = value.slice(lineStart, start);
    const list = line.match(/^(\s*)([-*+])\s+(.*)$/);
    if (list) {
      if (!list[3].trim()) {
        const next = value.slice(0, lineStart) + value.slice(start);
        commit(next, lineStart);
        return true;
      }
      replaceSelection(`\n${list[1]}${list[2]} `);
      return true;
    }
    const ordered = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
    if (ordered) {
      if (!ordered[3].trim()) {
        const next = value.slice(0, lineStart) + value.slice(start);
        commit(next, lineStart);
        return true;
      }
      replaceSelection(`\n${ordered[1]}${Number(ordered[2]) + 1}. `);
      return true;
    }
    const quote = line.match(/^(\s*>\s?)(.*)$/);
    if (quote) {
      if (!quote[2].trim()) {
        const next = value.slice(0, lineStart) + value.slice(start);
        commit(next, lineStart);
        return true;
      }
      replaceSelection(`\n${quote[1]}`);
      return true;
    }
    return false;
  }, [commit, replaceSelection, value]);

  const wrapSelection = useCallback((left: string, right = left) => {
    const target = textareaRef.current;
    if (!target) return;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const selected = value.slice(start, end);
    const next = value.slice(0, start) + left + selected + right + value.slice(end);
    if (selected) {
      commit(next, start + left.length, end + left.length);
    } else {
      commit(next, start + left.length);
    }
  }, [commit, value]);

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Tab") {
      event.preventDefault();
      indentLines(event.shiftKey);
      return;
    }
    if (event.key === "Enter" && continueMarkdownLine()) {
      event.preventDefault();
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
      event.preventDefault();
      wrapSelection("**");
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "i") {
      event.preventDefault();
      wrapSelection("*");
    }
  }, [continueMarkdownLine, indentLines, wrapSelection]);

  return (
    <textarea
      ref={textareaRef}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onSelect={(event) => emitSelection(event.currentTarget)}
      onKeyUp={(event) => emitSelection(event.currentTarget)}
      onKeyDown={handleKeyDown}
      onMouseUp={(event) => emitSelection(event.currentTarget)}
      spellCheck
      placeholder="Start writing..."
      className="h-full min-h-[calc(100vh-168px)] w-full resize-none border-0 bg-transparent px-8 py-7 font-sans text-[18px] leading-8 text-text outline-none selection:bg-accent/25 placeholder:text-text-dim/70"
    />
  );
}

function ProposalReview({
  proposal,
  meaningful,
  onAccept,
  onReject,
}: {
  proposal: ChannelNoteAssistProposal;
  meaningful: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className="rounded-md bg-accent/[0.08] px-3 py-2 text-[12px] leading-relaxed text-text-muted">
        {meaningful ? proposal.rationale : "The assistant did not find a useful structural change. Your draft is unchanged."}
      </div>
      {meaningful && (
        <div className="min-h-0 flex-1 overflow-auto rounded-md bg-input px-3 py-3">
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium text-accent">
            <Sparkles size={12} />
            Pending AI draft
          </div>
          <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-text">
            {stripFrontmatter(proposal.replacement_markdown)}
          </pre>
        </div>
      )}
      <div className="flex shrink-0 gap-2">
        {meaningful && (
          <button type="button" onClick={onAccept} className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-[12px] text-accent hover:bg-surface-overlay">
            <Check size={13} />
            Accept
          </button>
        )}
        <button type="button" onClick={onReject} className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-[12px] text-text-muted hover:bg-surface-overlay">
          <X size={13} />
          {meaningful ? "Reject" : "Dismiss"}
        </button>
      </div>
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

function wordCount(value: string): number {
  return (value.match(/\b[\w'-]+\b/g) ?? []).length;
}

function normalizeMd(value: string): string {
  return stripFrontmatter(value).replace(/\s+/g, " ").trim();
}
