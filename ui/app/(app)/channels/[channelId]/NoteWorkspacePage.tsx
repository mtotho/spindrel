import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookOpen,
  Check,
  Eye,
  FileText,
  MessageSquare,
  PenLine,
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
} from "@/src/api/hooks/useChannels";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
import { ChatSession } from "@/src/components/chat/ChatSession";
import { useModelGroups } from "@/src/api/hooks/useModels";
import { DocsMarkdownModal } from "@/src/components/shared/DocsMarkdownModal";
import { useBot } from "@/src/api/hooks/useBots";
import type { Message } from "@/src/types/api";

type SelectionState = { start: number; end: number; text: string };
type AutoSaveState = "idle" | "pending" | "saving" | "saved" | "error";
type SelectionRequest = { id: number; start: number; end: number };
type AppliedNotice = { message: string; undoBody?: string };

export default function NoteWorkspacePage() {
  const { channelId, slug } = useParams<{ channelId: string; slug: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const channelQuery = useChannel(channelId);
  const noteQuery = useChannelNote(channelId, slug ?? null);
  const writeNote = useWriteChannelNote(channelId ?? "");
  const assistNote = useAssistChannelNote(channelId ?? "");
  const note = noteQuery.data ?? null;
  const versionsQuery = useChannelWorkspaceFileVersions(channelId, note?.workspace_path ?? note?.path ?? null, !!note);
  const modelGroupsQuery = useModelGroups();
  const botQuery = useBot(channelQuery.data?.bot_id);

  const [bodyDraft, setBodyDraft] = useState("");
  const [frontmatter, setFrontmatter] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [baseHash, setBaseHash] = useState<string | null>(null);
  const [selection, setSelection] = useState<SelectionState>({ start: 0, end: 0, text: "" });
  const [preview, setPreview] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [aiFlash, setAiFlash] = useState(false);
  const [assistModel, setAssistModel] = useState("");
  const [assistProviderId, setAssistProviderId] = useState<string | null>(null);
  const [appliedNotice, setAppliedNotice] = useState<AppliedNotice | null>(null);
  const [selectionRequest, setSelectionRequest] = useState<SelectionRequest | null>(null);
  const [autoSaveState, setAutoSaveState] = useState<AutoSaveState>("idle");
  const [autoSaveError, setAutoSaveError] = useState<string | null>(null);
  const savedContentRef = useRef("");
  const loadedContentHashRef = useRef<string | null>(null);
  const saveInFlightRef = useRef(false);
  const latestDraftRef = useRef("");

  useEffect(() => {
    if (!note) return;
    if (loadedContentHashRef.current === note.content_hash && savedContentRef.current === note.content) return;
    loadedContentHashRef.current = note.content_hash;
    const split = splitFrontmatter(note.content);
    setFrontmatter(split.frontmatter);
    setBodyDraft(split.body);
    setTitleDraft(note.title);
    setBaseHash(note.content_hash);
    savedContentRef.current = note.content;
    setAutoSaveState("saved");
    setAutoSaveError(null);
    setAppliedNotice(null);
    setSelectionRequest(null);
    setSelection({ start: 0, end: 0, text: "" });
  }, [note]);

  const fullDraft = useMemo(
    () => `${setFrontmatterField(frontmatter, "title", titleDraft.trim() || "Untitled")}${bodyDraft}`,
    [bodyDraft, frontmatter, titleDraft],
  );
  useEffect(() => {
    latestDraftRef.current = fullDraft;
  }, [fullDraft]);
  const dirty = Boolean(note && fullDraft !== savedContentRef.current);
  const selectedText = selection.text.trim();
  const noteVersionPath = note?.workspace_path ?? note?.path ?? null;
  const noteSelectionSyntheticMessages = useMemo<Message[]>(() => {
    if (!chatOpen || !note?.session_id || !selectedText) return [];
    const clipped = selectedText.length > 1400 ? `${selectedText.slice(0, 1400).trimEnd()}\n...` : selectedText;
    return [{
      id: `note-selection-${selection.start}-${selection.end}-${note.content_hash}`,
      session_id: note.session_id,
      role: "system",
      content: `Selected note text\n\n\`\`\`markdown\n${clipped}\n\`\`\``,
      created_at: new Date().toISOString(),
      metadata: {
        ui_only: true,
        kind: "note_selection_context",
        source: "note_editor_selection",
        selection_start: selection.start,
        selection_end: selection.end,
      },
    }];
  }, [chatOpen, note?.content_hash, note?.session_id, selectedText, selection.end, selection.start]);
  const modelOptions = useMemo(() => {
    return (modelGroupsQuery.data ?? []).flatMap((group) =>
      group.models.map((model) => ({
        modelId: model.id,
        providerId: group.provider_id ?? null,
        label: model.display && model.display !== model.id ? `${model.display} (${model.id})` : model.id,
        providerName: group.provider_name,
      })),
    );
  }, [modelGroupsQuery.data]);

  const saveDraft = useCallback(async (content: string, hash: string | null) => {
    if (!channelId || !slug) return;
    saveInFlightRef.current = true;
    setAutoSaveState("saving");
    setAutoSaveError(null);
    try {
      const saved = await writeNote.mutateAsync({ slug, content, base_hash: hash });
      const split = splitFrontmatter(saved.content);
      setBaseHash(saved.content_hash);
      savedContentRef.current = saved.content;
      if (latestDraftRef.current === content) {
        setFrontmatter(split.frontmatter);
        setBodyDraft(split.body);
      }
      setAutoSaveState("saved");
    } finally {
      saveInFlightRef.current = false;
    }
  }, [channelId, slug, writeNote]);

  useEffect(() => {
    if (!note || !channelId || !slug) return;
    if (fullDraft === savedContentRef.current) {
      setAutoSaveState("saved");
      return;
    }
    if (saveInFlightRef.current) {
      setAutoSaveState("pending");
      return;
    }
    setAutoSaveState("pending");
    setAutoSaveError(null);
    const timer = window.setTimeout(() => {
      void saveDraft(fullDraft, baseHash).catch((error) => {
        setAutoSaveState("error");
        setAutoSaveError(error instanceof Error ? error.message : "Autosave failed");
      });
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [baseHash, channelId, fullDraft, note, saveDraft, slug]);

  const refreshNoteFromDisk = useCallback(() => {
    if (!channelId || !slug) return;
    void queryClient.invalidateQueries({ queryKey: ["channel-note", channelId, slug] });
    void queryClient.invalidateQueries({ queryKey: ["channel-notes", channelId] });
    if (noteVersionPath) {
      void queryClient.invalidateQueries({ queryKey: ["channel-workspace-file-versions", channelId, noteVersionPath] });
    }
  }, [channelId, noteVersionPath, queryClient, slug]);

  useEffect(() => {
    if (!chatOpen || dirty) return;
    refreshNoteFromDisk();
    const timer = window.setInterval(refreshNoteFromDisk, 1800);
    return () => window.clearInterval(timer);
  }, [chatOpen, dirty, refreshNoteFromDisk]);

  const closeChat = useCallback(() => {
    setChatOpen(false);
    refreshNoteFromDisk();
  }, [refreshNoteFromDisk]);

  const handleAssist = useCallback(async (mode: string, overrideInstruction?: string) => {
    if (!slug) return;
    const activeSelection = selectedText ? selection : null;
    const instruction = overrideInstruction;
    const next = await assistNote.mutateAsync({
      slug,
      mode,
      instruction,
      selection: activeSelection,
      base_hash: baseHash,
      content: fullDraft,
      model_override: assistModel || undefined,
      model_provider_id_override: assistModel ? assistProviderId : null,
    });
    const original = next.target === "selection" && activeSelection?.text ? activeSelection.text : bodyDraft;
    const meaningful = normalizeMd(next.replacement_markdown) !== normalizeMd(original);
    if (!meaningful) {
      setAppliedNotice({ message: "No useful note change found." });
      window.setTimeout(() => setAppliedNotice(null), 2200);
      return;
    }
    const previousBody = bodyDraft;
    let nextBody: string;
    let changedStart = 0;
    let changedEnd = 0;
    if (next.target === "selection" && activeSelection?.text) {
      nextBody = bodyDraft.slice(0, activeSelection.start) + next.replacement_markdown + bodyDraft.slice(activeSelection.end);
      changedStart = activeSelection.start;
      changedEnd = activeSelection.start + next.replacement_markdown.length;
    } else {
      nextBody = stripFrontmatter(next.replacement_markdown);
      const bounds = changedRange(bodyDraft, nextBody);
      changedStart = bounds.start;
      changedEnd = bounds.end;
    }
    setBodyDraft(nextBody);
    setSelectionRequest({ id: Date.now(), start: changedStart, end: changedEnd });
    setAppliedNotice({ message: next.rationale || "Updated the note draft.", undoBody: previousBody });
    setAiFlash(true);
    window.setTimeout(() => setAiFlash(false), 900);
    window.setTimeout(() => setAppliedNotice((current) => current?.undoBody === previousBody ? null : current), 5200);
  }, [assistModel, assistNote, assistProviderId, baseHash, bodyDraft, fullDraft, selectedText, selection, slug]);

  const handleSelectionAssist = useCallback(() => {
    const instruction = selectedText
      ? "Treat the selected Markdown as the user's focus. If it is a placeholder or instruction, replace it with useful note content, specific questions, or a practical scaffold. Do not return a no-op."
      : "Improve the current note with useful structure and concrete next details. Do not return a no-op.";
    void handleAssist(selectedText ? "expand_selection" : "clarify_structure", instruction);
  }, [handleAssist, selectedText]);

  const undoAppliedChange = useCallback(() => {
    if (!appliedNotice?.undoBody) return;
    setBodyDraft(appliedNotice.undoBody);
    setAppliedNotice(null);
    setSelectionRequest({ id: Date.now(), start: 0, end: Math.min(appliedNotice.undoBody.length, 1) });
    setAiFlash(true);
    window.setTimeout(() => setAiFlash(false), 900);
  }, [appliedNotice]);

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
  const effectiveDefaultModel = channelQuery.data?.model_override || botQuery.data?.model || "default";
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
          onClick={() => setHelpOpen(true)}
          className="flex h-8 w-8 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay hover:text-text"
          aria-label="Open notes documentation"
          title="Notes documentation"
        >
          <BookOpen size={15} />
        </button>
        <button
          type="button"
          onClick={() => setPreview((v) => !v)}
          className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] text-text-muted hover:bg-surface-overlay"
        >
          {preview ? <PenLine size={14} /> : <Eye size={14} />}
          {preview ? "Edit" : "Preview"}
        </button>
        <AutoSaveIndicator state={autoSaveState} dirty={dirty} error={autoSaveError} />
        <select
          value={assistModel ? `${assistProviderId ?? ""}::${assistModel}` : ""}
          onChange={(event) => {
            const value = event.target.value;
            if (!value) {
              setAssistModel("");
              setAssistProviderId(null);
              return;
            }
            const [provider, model] = value.split("::");
            setAssistModel(model);
            setAssistProviderId(provider || null);
          }}
          className="max-w-[190px] rounded-md bg-transparent px-2 py-1.5 text-[11px] text-text-dim outline-none hover:bg-surface-overlay"
          title="Magic edit model"
        >
          <option value="">model default ({effectiveDefaultModel})</option>
          {modelOptions.map((option) => (
            <option key={`${option.providerId ?? ""}::${option.modelId}`} value={`${option.providerId ?? ""}::${option.modelId}`}>
              {option.modelId}
            </option>
          ))}
        </select>
      </header>

      <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 pb-2 text-[11px] text-text-dim sm:px-6 lg:px-8">
        <span>{channelName}</span>
        <span>{wordCount(bodyDraft)} words</span>
        <span>{versionsQuery.data?.versions.length ?? 0} revisions</span>
        <span>{targetLabel}</span>
        <Link to={`/channels/${encodeURIComponent(channelId)}`} className="text-accent hover:underline">Channel</Link>
      </div>

      <main className="min-h-0 flex-1 overflow-hidden px-4 pb-4 sm:px-6 lg:px-8">
        <section className={`relative min-h-0 overflow-hidden rounded-md bg-surface-raised/45 ${aiFlash ? "note-ai-flash" : ""}`}>
          {preview ? (
            <div className="h-full overflow-auto bg-surface px-8 py-7">
              <MarkdownViewer content={bodyDraft} />
            </div>
          ) : (
            <MarkdownNoteEditor
              value={bodyDraft}
              onChange={setBodyDraft}
              onSelectionChange={setSelection}
              focusSelection={selectionRequest}
            />
          )}
          {assistNote.isPending && (
            <div className="pointer-events-none absolute inset-x-6 top-6 flex items-center gap-2 rounded-md bg-accent/[0.10] px-3 py-2 text-[12px] text-accent">
              <Sparkles size={14} className="thinking-pulse" />
              Updating the note draft...
            </div>
          )}
          {selectedText && !preview && !assistNote.isPending && (
            <SelectionAssistBar
              selectedLength={selectedText.length}
              onAssist={handleSelectionAssist}
              onChat={() => setChatOpen(true)}
              onDismiss={() => setSelection({ start: 0, end: 0, text: "" })}
            />
          )}
          {appliedNotice && (
            <div className="absolute inset-x-6 bottom-6 flex items-center gap-2 rounded-md border border-accent/20 bg-surface/90 px-3 py-2 text-[12px] text-text-muted shadow-lg shadow-black/20 backdrop-blur">
              <Sparkles size={14} className="shrink-0 text-accent" />
              <span className="min-w-0 flex-1 truncate">{appliedNotice.message}</span>
              {appliedNotice.undoBody && (
                <button
                  type="button"
                  onClick={undoAppliedChange}
                  className="shrink-0 rounded-md px-2 py-1 text-[12px] font-medium text-accent hover:bg-accent/[0.10]"
                >
                  Undo
                </button>
              )}
            </div>
          )}
        </section>
      </main>

      {!chatOpen && note.session_id && botId && (
        <button
          type="button"
          onClick={() => setChatOpen(true)}
          className="fixed bottom-5 right-5 z-30 inline-flex items-center gap-2 rounded-md border border-surface-border/60 bg-surface-overlay px-3 py-2 text-[12px] font-medium text-text hover:bg-surface-raised"
        >
          <MessageSquare size={14} className="text-accent" />
          Note chat
        </button>
      )}

      {note.session_id && botId && (
        <ChatSession
          source={{
            kind: "ephemeral",
            sessionStorageKey: `note:${channelId}:${note.slug}`,
            parentChannelId: channelId,
            defaultBotId: botId,
            pinnedSessionId: note.session_id,
            context: {
              page_name: `Note: ${note.title}`,
              tags: ["notes", "markdown", "knowledge-base"],
              tool_hints: ["workspace/notes", "workspace/knowledge_bases", "workspace/channel_workspaces", "grill_me"],
              payload: {
                kind: "note_session",
                note_path: note.tool_path ?? note.workspace_path ?? note.path,
                workspace_note_path: note.workspace_path ?? note.path,
                internal_note_path: note.path,
                note_title: note.title,
                current_selection: selectedText ? { start: selection.start, end: selection.end, text: selectedText } : null,
                current_markdown: bodyDraft.slice(0, 12000),
                instruction: `Pinned notes mode. When the user asks you to write notes, edit ${note.tool_path ?? note.workspace_path ?? note.path} with workspace file tools. Do not use bot memory. If current_selection is present, treat it as the focused note text for the user's next request.`,
              },
            },
          }}
          shape="dock"
          open={chatOpen}
          onClose={closeChat}
          title={`Note: ${note.title}`}
          dockCollapsedTitle="Note assistant"
          dockCollapsedSubtitle={note.title}
          dismissMode="close"
          syntheticMessages={noteSelectionSyntheticMessages}
          disableOutsideDismiss
          chatMode="terminal"
          initiallyExpanded
        />
      )}
      {helpOpen && (
        <DocsMarkdownModal
          path="guides/notes"
          title="Notes"
          errorMessage="Failed to load notes documentation."
          onClose={() => setHelpOpen(false)}
        />
      )}
    </div>
  );
}

function MarkdownNoteEditor({
  value,
  onChange,
  onSelectionChange,
  focusSelection,
}: {
  value: string;
  onChange: (value: string) => void;
  onSelectionChange: (selection: SelectionState) => void;
  focusSelection: SelectionRequest | null;
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

  useEffect(() => {
    if (!focusSelection) return;
    const target = textareaRef.current;
    if (!target) return;
    const start = Math.max(0, Math.min(focusSelection.start, value.length));
    const end = Math.max(start, Math.min(focusSelection.end, value.length));
    window.requestAnimationFrame(() => {
      target.focus();
      target.selectionStart = start;
      target.selectionEnd = end;
      target.scrollTop = Math.max(0, target.scrollHeight * (start / Math.max(value.length, 1)) - target.clientHeight / 2);
      emitSelection(target);
    });
  }, [emitSelection, focusSelection, value]);

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

function AutoSaveIndicator({
  state,
  dirty,
  error,
}: {
  state: AutoSaveState;
  dirty: boolean;
  error: string | null;
}) {
  const label =
    state === "saving" ? "Saving..."
      : state === "pending" ? "Autosave pending"
        : state === "error" ? "Autosave failed"
          : dirty ? "Unsaved"
            : "Autosaved";
  const tone =
    state === "error" ? "text-red-400"
      : state === "saving" || state === "pending" ? "text-accent"
        : "text-emerald-400";
  return (
    <div
      className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12px] ${tone}`}
      title={error ?? label}
    >
      {state === "saving" || state === "pending" ? (
        <Sparkles size={13} className={state === "saving" ? "thinking-pulse" : ""} />
      ) : state === "error" ? (
        <X size={13} />
      ) : (
        <Check size={13} />
      )}
      <span className="hidden sm:inline">{label}</span>
    </div>
  );
}

function SelectionAssistBar({
  selectedLength,
  onAssist,
  onChat,
  onDismiss,
}: {
  selectedLength: number;
  onAssist: () => void;
  onChat: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="absolute bottom-6 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1 rounded-md border border-surface-border/60 bg-surface-overlay px-2 py-1.5 text-[12px] text-text-muted">
      <div className="flex items-center gap-1.5 px-1.5">
        <Wand2 size={14} className="text-emphasis" />
        <span>{selectedLength} selected</span>
      </div>
      <button
        type="button"
        onClick={onAssist}
        className="inline-flex items-center gap-1.5 rounded-md bg-accent/[0.12] px-2.5 py-1.5 font-medium text-accent hover:bg-accent/[0.18]"
      >
        <Sparkles size={13} />
        Add detail
      </button>
      <button
        type="button"
        onClick={onChat}
        className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-text-muted hover:bg-surface-raised hover:text-text"
      >
        <MessageSquare size={13} />
        Chat
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className="flex h-7 w-7 items-center justify-center rounded-md text-text-dim hover:bg-surface-raised hover:text-text"
        aria-label="Dismiss selection actions"
      >
        <X size={13} />
      </button>
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

function changedRange(before: string, after: string): { start: number; end: number } {
  let start = 0;
  while (start < before.length && start < after.length && before[start] === after[start]) {
    start += 1;
  }
  let beforeEnd = before.length;
  let afterEnd = after.length;
  while (beforeEnd > start && afterEnd > start && before[beforeEnd - 1] === after[afterEnd - 1]) {
    beforeEnd -= 1;
    afterEnd -= 1;
  }
  return { start, end: Math.max(start, afterEnd) };
}
