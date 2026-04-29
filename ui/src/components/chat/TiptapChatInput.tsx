import React, { useState, useRef, useCallback, useEffect, useLayoutEffect, forwardRef, useImperativeHandle, useMemo } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import MentionBase from "@tiptap/extension-mention";
import { Extension, InputRule } from "@tiptap/core";
import { Plugin, TextSelection } from "@tiptap/pm/state";
import { Markdown } from "tiptap-markdown";
import { useCompletions, useModelGroups } from "../../api/hooks/useModels";
import { AutocompleteMenu, clusterSkillPacks, scoreMatch } from "../shared/LlmPrompt";
import { useThemeTokens } from "../../theme/tokens";
import type { CompletionItem, SlashCommandArgSpec, SlashCommandSpec } from "../../types/api";
import { buildCompletedSlashCommandText, filterSlashCommands } from "./slashCommands";
import { filterArgItems, resolveArgSourceItems } from "./slashArgSources";
import { useSlashCommandList } from "@/src/api/hooks/useSlashCommands";
import type { SuggestionProps, SuggestionKeyDownProps } from "@tiptap/suggestion";
import "./tiptap-input.css";
import type { SlashCommandId, SlashCommandSurface } from "../../types/api";

// Extend Mention with markdown serialization so getMarkdown() outputs @value,
// and emit a data-type="<prefix>" attr so CSS can color chips by kind
// (skill / tool / bot / knowledge) to match the @-picker badges.
const Mention = MentionBase.extend({
  addStorage() {
    return {
      ...this.parent?.(),
      markdown: {
        serialize(state: any, node: any) {
          state.write(`@${node.attrs.id}`);
        },
      },
    };
  },
  renderHTML({ node, HTMLAttributes }) {
    const id: string = (node.attrs?.id ?? "") as string;
    const prefix = id.includes(":") ? id.split(":")[0] : "";
    return [
      "span",
      {
        ...HTMLAttributes,
        class: "mention",
        "data-type": prefix || "mention",
      },
      `@${(node.attrs?.label ?? id) as string}`,
    ];
  },
});

export interface TiptapChatInputProps {
  text: string;
  onTextChange: (markdown: string) => void;
  onSubmit: () => void;
  onImagePaste?: (files: File[]) => void;
  onSlashCommand?: (id: string, args?: string[]) => void;
  slashSurface?: SlashCommandSurface;
  availableSlashCommands?: SlashCommandId[];
  disabled?: boolean;
  autoFocus?: boolean;
  isMobile?: boolean;
  currentBotId?: string;
  /** When true (multi-bot channel), primary bot is NOT excluded from @-mentions */
  isMultiBot?: boolean;
  placeholder?: string;
  chatMode?: "default" | "terminal";
  onEscapeDraft?: () => void;
  onEscapeEmpty?: () => boolean | void;
  onArrowUpEmpty?: () => boolean | void;
}

export interface TiptapChatInputHandle {
  focus: () => void;
  clear: () => void;
  getMarkdown: () => string;
  setMarkdown: (text: string) => void;
  /** Insert a styled @mention node followed by a trailing space. `id` becomes the
   *  `@${id}` token on send (matches the regex in app/agent/tags.py). */
  insertMention: (id: string, label?: string) => void;
}

export const TiptapChatInput = forwardRef<TiptapChatInputHandle, TiptapChatInputProps>(
  function TiptapChatInput({ text, onTextChange, onSubmit, onImagePaste, onSlashCommand, slashSurface = "channel", availableSlashCommands, disabled, autoFocus, isMobile, currentBotId, isMultiBot, placeholder = "Type a message...", chatMode = "default", onEscapeDraft, onEscapeEmpty, onArrowUpEmpty }, ref) {
    // Phase 4: scope catalog by bot id so harness sessions get the
    // runtime-allowlisted slash list automatically.
    const slashCatalog = useSlashCommandList(currentBotId);
    const { data: modelGroups } = useModelGroups();
    const t = useThemeTokens();
    const { data: completions } = useCompletions();
    const containerRef = useRef<HTMLDivElement>(null);

    // Stable refs for closure access (suggestion callbacks + extension shortcuts)
    const completionsRef = useRef(completions);
    completionsRef.current = completions;
    const currentBotIdRef = useRef(currentBotId);
    currentBotIdRef.current = currentBotId;
    const isMultiBotRef = useRef(isMultiBot);
    isMultiBotRef.current = isMultiBot;
    const onSubmitRef = useRef(onSubmit);
    onSubmitRef.current = onSubmit;
    const onTextChangeRef = useRef(onTextChange);
    onTextChangeRef.current = onTextChange;
    const onImagePasteRef = useRef(onImagePaste);
    onImagePasteRef.current = onImagePaste;
    const onSlashCommandRef = useRef(onSlashCommand);
    const onEscapeDraftRef = useRef(onEscapeDraft);
    const onEscapeEmptyRef = useRef(onEscapeEmpty);
    const onArrowUpEmptyRef = useRef(onArrowUpEmpty);
    onSlashCommandRef.current = onSlashCommand;
    onEscapeDraftRef.current = onEscapeDraft;
    onEscapeEmptyRef.current = onEscapeEmpty;
    onArrowUpEmptyRef.current = onArrowUpEmpty;
    const isMobileRef = useRef(isMobile);
    isMobileRef.current = isMobile;
    const initialTextRef = useRef(text);

    // Guard: suppress onTextChange during programmatic setContent (draft restore, clear)
    const suppressUpdateRef = useRef(false);

    // @ mention autocomplete menu state
    const [showMenu, setShowMenu] = useState(false);
    const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 0 });
    const [filtered, setFiltered] = useState<CompletionItem[]>([]);
    const [activeIdx, setActiveIdx] = useState(0);
    const filteredRef = useRef<CompletionItem[]>([]);
    const activeIdxRef = useRef(0);
    const commandRef = useRef<((props: { id: string; label: string }) => void) | null>(null);

    // Slash command menu state (managed directly, not via suggestion plugin)
    const [showCmdMenu, setShowCmdMenu] = useState(false);
    const [cmdFiltered, setCmdFiltered] = useState<CompletionItem[]>([]);
    const [cmdActiveIdx, setCmdActiveIdx] = useState(0);
    const cmdFilteredRef = useRef<CompletionItem[]>([]);
    const cmdActiveIdxRef = useRef(0);
    // When the user has typed `/<cmd> ` and we're showing arg completions instead
    // of command completions, this ref captures which command is being argued and
    // the arg spec we're completing. Null = Mode A (command picker).
    const cmdArgModeRef = useRef<{ commandId: SlashCommandId; argSpec: SlashCommandArgSpec } | null>(null);
    // Sync refs mirror React state so the keymap handler sees the latest value instantly
    const showMenuRef = useRef(false);
    const showCmdMenuRef = useRef(false);

    useEffect(() => { filteredRef.current = filtered; }, [filtered]);
    useEffect(() => { activeIdxRef.current = activeIdx; }, [activeIdx]);
    useEffect(() => { cmdFilteredRef.current = cmdFiltered; }, [cmdFiltered]);
    useEffect(() => { cmdActiveIdxRef.current = cmdActiveIdx; }, [cmdActiveIdx]);

    // Keep stable refs for values consumed inside editor extension closures —
    // the extension array is memoized by placeholder/suggestion only, so bare
    // references here would stale-close over the first render's values.
    const slashCatalogRef = useRef<SlashCommandSpec[]>(slashCatalog);
    useEffect(() => { slashCatalogRef.current = slashCatalog; }, [slashCatalog]);

    const updateMenuPos = useCallback(() => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setMenuPos({
          top: rect.top - 4,
          left: rect.left,
          width: Math.min(rect.width, 500),
        });
      }
    }, []);

    // Slash command detection — called from onUpdate and from the ProseMirror plugin.
    // Two modes:
    //   A) `/<partial>`           → show matching commands (command picker)
    //   B) `/<cmd> <partial>`     → show arg completions for <cmd>'s first arg
    const detectSlashCommand = useCallback((text: string) => {
      const trimmed = text.trim();

      const hide = () => {
        if (showCmdMenuRef.current) {
          showCmdMenuRef.current = false;
          cmdFilteredRef.current = [];
          setShowCmdMenu(false);
          setCmdFiltered([]);
        }
        cmdArgModeRef.current = null;
      };

      if (!trimmed.startsWith("/") || trimmed.includes("\n")) {
        hide();
        return;
      }

      const body = trimmed.slice(1);
      const spaceIdx = body.indexOf(" ");

      if (spaceIdx === -1) {
        // Mode A: command picker
        cmdArgModeRef.current = null;
        const items = filterSlashCommands(body, slashSurface, slashCatalog, availableSlashCommands);
        cmdFilteredRef.current = items;
        cmdActiveIdxRef.current = 0;
        showCmdMenuRef.current = items.length > 0;
        setCmdFiltered(items);
        setCmdActiveIdx(0);
        updateMenuPos();
        setShowCmdMenu(items.length > 0);
        return;
      }

      // Mode B: arg picker for the matched command
      const cmdId = body.slice(0, spaceIdx).toLowerCase();
      const partial = body.slice(spaceIdx + 1);
      const allow = availableSlashCommands ? new Set<SlashCommandId>(availableSlashCommands) : null;
      const spec = slashCatalog.find(
        (s) =>
          s.id === cmdId &&
          Array.isArray(s.surfaces) &&
          s.surfaces.includes(slashSurface) &&
          (!allow || allow.has(s.id)),
      );
      const specArgs = Array.isArray(spec?.args) ? spec!.args : [];
      if (!spec || specArgs.length === 0) {
        hide();
        return;
      }
      const argSpec = specArgs[0];
      if (argSpec.source === "free_text") {
        // Free-text args get no completions — just hide the menu and let the
        // user type. The overall `/<cmd> <title>` still resolves on submit.
        hide();
        return;
      }
      const items = filterArgItems(
        resolveArgSourceItems(argSpec.source, argSpec.enum, modelGroups),
        partial,
      );
      cmdArgModeRef.current = { commandId: spec.id, argSpec };
      cmdFilteredRef.current = items;
      cmdActiveIdxRef.current = 0;
      showCmdMenuRef.current = items.length > 0;
      setCmdFiltered(items);
      setCmdActiveIdx(0);
      updateMenuPos();
      setShowCmdMenu(items.length > 0);
    }, [availableSlashCommands, slashCatalog, slashSurface, modelGroups, updateMenuPos]);

    // Mention suggestion config — stable via refs
    const suggestion = useMemo(() => ({
      char: "@",
      items: ({ query }: { query: string }) => {
        const comps = completionsRef.current;
        if (!comps) return [];
        // In multi-bot channels, allow @-mentioning the primary bot too
        const excludeValue = (!isMultiBotRef.current && currentBotIdRef.current) ? `bot:${currentBotIdRef.current}` : "";
        const ranked = comps
          .filter((c: CompletionItem) => !excludeValue || c.value !== excludeValue)
          .map((c: CompletionItem) => ({ c, s: scoreMatch(c.value, c.label, query) }))
          .filter((x: { s: number }) => x.s > 0)
          .sort((a: { s: number }, b: { s: number }) => b.s - a.s)
          .map((x: { c: CompletionItem }) => x.c)
          .slice(0, 10);
        return clusterSkillPacks(ranked);
      },
      render: () => ({
        onStart: (props: SuggestionProps<CompletionItem>) => {
          commandRef.current = props.command as any;
          setFiltered(props.items);
          filteredRef.current = props.items;
          setActiveIdx(0);
          activeIdxRef.current = 0;
          updateMenuPos();
          showMenuRef.current = props.items.length > 0;
          setShowMenu(props.items.length > 0);
        },
        onUpdate: (props: SuggestionProps<CompletionItem>) => {
          commandRef.current = props.command as any;
          setFiltered(props.items);
          filteredRef.current = props.items;
          setActiveIdx(0);
          activeIdxRef.current = 0;
          updateMenuPos();
          showMenuRef.current = props.items.length > 0;
          setShowMenu(props.items.length > 0);
        },
        onExit: () => {
          showMenuRef.current = false;
          setShowMenu(false);
          commandRef.current = null;
        },
        onKeyDown: ({ event }: SuggestionKeyDownProps) => {
          if (event.key === "ArrowDown") {
            const next = Math.min(activeIdxRef.current + 1, filteredRef.current.length - 1);
            setActiveIdx(next);
            activeIdxRef.current = next;
            return true;
          }
          if (event.key === "ArrowUp") {
            const next = Math.max(activeIdxRef.current - 1, 0);
            setActiveIdx(next);
            activeIdxRef.current = next;
            return true;
          }
          if (event.key === "Enter" || event.key === "Tab") {
            if (filteredRef.current.length > 0) {
              const item = filteredRef.current[activeIdxRef.current];
              commandRef.current?.({ id: item.value, label: item.label });
              return true;
            }
          }
          if (event.key === "Escape") {
            setShowMenu(false);
            return true;
          }
          return false;
        },
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }), [updateMenuPos]);

    const extensions = useMemo(() => [
      // MUST be first — our keymap handlers need to fire before StarterKit's
      // HardBreak (which would otherwise exitCode on Shift-Enter in code blocks)
      Extension.create({
        name: "chatInputBehavior",
        priority: 1000,
        addKeyboardShortcuts() {
          return {
            "Mod-Enter": () => {
              onSubmitRef.current();
              return true;
            },
            "Ctrl-Enter": () => {
              onSubmitRef.current();
              return true;
            },
            // Enter outside code block → submit (code block Enter handled by raw plugin below)
            Enter: ({ editor: ed }) => {
              if (ed.isActive("codeBlock")) return false;
              // Let the suggestion plugin handle Enter when @-mention menu is open
              if (showMenuRef.current) return false;
              // If slash command menu is open, execute the selected command (or arg)
              if (showCmdMenuRef.current && cmdFilteredRef.current.length > 0) {
                const item = cmdFilteredRef.current[cmdActiveIdxRef.current];
                const argMode = cmdArgModeRef.current;
                if (argMode) {
                  // Mode B: submit `/<cmd> <picked-arg>`
                  suppressUpdateRef.current = true;
                  ed.commands.clearContent(true);
                  suppressUpdateRef.current = false;
                  showCmdMenuRef.current = false;
                  setShowCmdMenu(false);
                  cmdArgModeRef.current = null;
                  onSlashCommandRef.current?.(argMode.commandId, [item.value]);
                  return true;
                }
                // Mode A: picking a command. If it requires args, fill the
                // editor with `/<cmd> ` so the user can provide the arg
                // (which transitions detection into Mode B). Otherwise submit.
                const pickedSpec = slashCatalogRef.current.find((s) => s.id === item.value);
                const requiresArg = Array.isArray(pickedSpec?.args)
                  ? pickedSpec!.args.some((a) => a.required)
                  : false;
                if (requiresArg) {
                  // Emit the update so detectSlashCommand re-runs and the
                  // dropdown transitions into Mode B (arg picker).
                  ed.commands.setContent(`/${item.value} `, { emitUpdate: true });
                  ed.commands.focus("end");
                  return true;
                }
                suppressUpdateRef.current = true;
                ed.commands.clearContent(true);
                suppressUpdateRef.current = false;
                showCmdMenuRef.current = false;
                setShowCmdMenu(false);
                onSlashCommandRef.current?.(item.value);
                return true;
              }
              // On mobile, Enter inserts a newline (no Shift+Enter on mobile keyboards)
              if (isMobileRef.current) return false;
              onSubmitRef.current();
              return true;
            },
            Escape: ({ editor: ed }) => {
              // Close slash command menu on Escape
              if (showCmdMenuRef.current) {
                showCmdMenuRef.current = false;
                setShowCmdMenu(false);
                return true;
              }
              if (ed.isActive("codeBlock")) {
                const { $from } = ed.state.selection;
                if (!$from.parent.textContent) {
                  ed.commands.toggleCodeBlock();
                } else {
                  const after = $from.after();
                  const nodeAfter = ed.state.doc.nodeAt(after);
                  if (nodeAfter) {
                    ed.commands.setTextSelection(after + 1);
                  } else {
                    ed.chain()
                      .insertContentAt(after, { type: "paragraph" })
                      .setTextSelection(after + 1)
                      .run();
                  }
                }
                return true;
              }
              const marks = ed.state.storedMarks || ed.state.selection.$from.marks();
              if (marks.length > 0) {
                ed.commands.unsetAllMarks();
                return true;
              }
              const currentText = ((ed.storage as any).markdown.getMarkdown?.() ?? "").trim();
              if (currentText) {
                suppressUpdateRef.current = true;
                ed.commands.clearContent(true);
                ed.commands.unsetAllMarks();
                suppressUpdateRef.current = false;
                onTextChangeRef.current("");
                initialTextRef.current = "";
                onEscapeDraftRef.current?.();
                return true;
              }
              if (!currentText && onEscapeEmptyRef.current) {
                return onEscapeEmptyRef.current() !== false;
              }
              return false;
            },
            ArrowDown: () => {
              if (showCmdMenuRef.current && cmdFilteredRef.current.length > 0) {
                const next = Math.min(cmdActiveIdxRef.current + 1, cmdFilteredRef.current.length - 1);
                setCmdActiveIdx(next);
                cmdActiveIdxRef.current = next;
                return true;
              }
              return false;
            },
            ArrowUp: ({ editor: ed }) => {
              if (showCmdMenuRef.current && cmdFilteredRef.current.length > 0) {
                const next = Math.max(cmdActiveIdxRef.current - 1, 0);
                setCmdActiveIdx(next);
                cmdActiveIdxRef.current = next;
                return true;
              }
              const currentText = ((ed.storage as any).markdown.getMarkdown?.() ?? "").trim();
              if (!currentText && onArrowUpEmptyRef.current) {
                return onArrowUpEmptyRef.current() !== false;
              }
              return false;
            },
            Tab: ({ editor: ed }) => {
              // Tab completes slash command text. Enter remains the execution key.
              if (showCmdMenuRef.current && cmdFilteredRef.current.length > 0) {
                const item = cmdFilteredRef.current[cmdActiveIdxRef.current];
                const argMode = cmdArgModeRef.current;
                if (argMode) {
                  ed.commands.setContent(buildCompletedSlashCommandText(argMode.commandId, item.value), { emitUpdate: true });
                  ed.commands.focus("end");
                  showCmdMenuRef.current = false;
                  setShowCmdMenu(false);
                  cmdArgModeRef.current = null;
                  return true;
                }
                ed.commands.setContent(buildCompletedSlashCommandText(item.value), { emitUpdate: true });
                ed.commands.focus("end");
                showCmdMenuRef.current = false;
                setShowCmdMenu(false);
                return true;
              }
              if (ed.isActive("codeBlock")) {
                return ed.commands.insertContent("  ");
              }
              return false;
            },
          };
        },
        // Raw ProseMirror plugin — handleKeyDown fires at plugin level before any
        // keymap processing, guaranteeing we intercept Enter/Shift-Enter in code blocks
        // before HardBreak's exitCode can fire.
        addProseMirrorPlugins() {
          const editorInstance = this.editor;
          return [
            new Plugin({
              props: {
                handleKeyDown(view, event) {
                  if (event.key !== "Enter") return false;
                  if (!editorInstance.isActive("codeBlock")) return false;

                  event.preventDefault();

                  // Double-Enter exit (plain Enter only, not Shift+Enter):
                  // if cursor is at end and last line is empty, exit the code block
                  if (!event.shiftKey) {
                    const { $from } = editorInstance.state.selection;
                    const text = $from.parent.textContent;
                    const offset = $from.parentOffset;
                    if (offset === text.length && text.endsWith("\n")) {
                      editorInstance.chain()
                        .command(({ tr }) => {
                          tr.delete($from.pos - 1, $from.pos);
                          return true;
                        })
                        .exitCode()
                        .run();
                      return true;
                    }
                  }

                  // Insert newline (both Enter and Shift+Enter)
                  view.dispatch(view.state.tr.insertText("\n"));
                  return true;
                },
              },
            }),
          ];
        },
        // Triple backtick at start of line → immediately create code block (no Enter needed)
        addInputRules() {
          return [
            new InputRule({
              find: /^```$/,
              handler: ({ state, range, commands }) => {
                // Replace the entire paragraph node with an empty code block
                commands.command(({ tr }) => {
                  const $from = state.doc.resolve(range.from);
                  const blockStart = $from.before();
                  const blockEnd = $from.after();
                  tr.replaceWith(blockStart, blockEnd, state.schema.nodes.codeBlock.create());
                  tr.setSelection(TextSelection.create(tr.doc, blockStart + 1));
                  return true;
                });
              },
            }),
          ];
        },
      }),
      StarterKit.configure({ hardBreak: { keepMarks: true } }),
      Markdown.configure({
        html: false,
        transformPastedText: true,
        transformCopiedText: true,
      }),
      Placeholder.configure({ placeholder }),
      Mention.configure({
        HTMLAttributes: { class: "mention" },
        renderText({ node }) {
          return `@${node.attrs.id}`;
        },
        suggestion,
      }),
    ], [placeholder, suggestion]);

    const editor = useEditor({
      extensions,
      content: "",
      editable: !disabled,
      autofocus: autoFocus ? "end" : false,
      onUpdate: ({ editor: ed }) => {
        if (suppressUpdateRef.current) return;
        const md = (ed.storage as any).markdown.getMarkdown();
        onTextChangeRef.current(md);
        // Detect slash commands in the text
        detectSlashCommand(md);
      },
      // Intercept paste at ProseMirror level — images go to pendingFiles, not the editor
      editorProps: {
        handlePaste: (view, event) => {
          const items = event.clipboardData?.items;
          if (!items) return false;
          const imageFiles: File[] = [];
          for (const item of Array.from(items)) {
            if (item.type.startsWith("image/")) {
              const file = item.getAsFile();
              if (file) imageFiles.push(file);
            }
          }
          if (imageFiles.length > 0) {
            event.preventDefault();
            onImagePasteRef.current?.(imageFiles);
            return true; // handled — prevent ProseMirror from processing
          }
          return false; // let ProseMirror handle text/html paste
        },
      },
    });

    useEffect(() => {
      if (!editor || editor.isDestroyed) return;
      const markdown = (editor.storage as any)?.markdown?.getMarkdown?.() ?? "";
      detectSlashCommand(markdown);
    }, [editor, detectSlashCommand]);

    // Set initial content from markdown draft — useLayoutEffect to avoid flash
    useLayoutEffect(() => {
      if (editor && initialTextRef.current) {
        suppressUpdateRef.current = true;
        editor.commands.setContent(initialTextRef.current);
        suppressUpdateRef.current = false;
      }
    }, [editor]);

    // Sync disabled state
    useEffect(() => {
      if (editor && !editor.isDestroyed) {
        editor.setEditable(!disabled);
      }
    }, [disabled, editor]);

    // Global "/" hotkey: anywhere on the chat screen, pressing "/" focuses this
    // composer and inserts a leading slash so the command picker opens. Guarded
    // so we don't steal "/" from other inputs, modals, or when the editor is
    // already focused (native input handles it).
    useEffect(() => {
      if (!editor || disabled) return;
      const container = containerRef.current;
      if (!container) return;
      const handler = (e: KeyboardEvent) => {
        if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
        const target = e.target as HTMLElement | null;
        if (target) {
          const tag = target.tagName;
          if (
            tag === "INPUT" ||
            tag === "TEXTAREA" ||
            tag === "SELECT" ||
            target.isContentEditable
          ) {
            return;
          }
        }
        // Skip if another composer is visible and would also claim this event
        // (first one wins — but guard against an offscreen/hidden instance).
        if (container.offsetParent === null) return;
        e.preventDefault();
        editor.chain().focus("end").insertContent("/").run();
      };
      window.addEventListener("keydown", handler);
      return () => window.removeEventListener("keydown", handler);
    }, [editor, disabled]);

    useImperativeHandle(ref, () => ({
      focus: () => editor?.commands.focus("end"),
      clear: () => {
        suppressUpdateRef.current = true;
        editor?.commands.clearContent(true);
        editor?.commands.unsetAllMarks();
        suppressUpdateRef.current = false;
        // Reset so editor recreation (e.g. mobile refocus) doesn't restore stale draft
        initialTextRef.current = "";
      },
      getMarkdown: () => (editor?.storage as any)?.markdown?.getMarkdown() ?? "",
      setMarkdown: (text: string) => {
        if (!editor) return;
        suppressUpdateRef.current = true;
        editor.commands.setContent(text || "", { emitUpdate: false });
        editor.commands.unsetAllMarks();
        suppressUpdateRef.current = false;
        initialTextRef.current = text || "";
        onTextChangeRef.current(text || "");
        editor.commands.focus("end");
      },
      insertMention: (id: string, label?: string) => {
        if (!editor) return;
        editor.chain().focus()
          .insertContent([
            { type: "mention", attrs: { id, label: label ?? id } },
            { type: "text", text: " " },
          ])
          .run();
      },
    }), [editor]);

    const cssVars = useMemo(() => ({
      "--tiptap-text": t.text,
      "--tiptap-text-dim": t.textDim,
      "--tiptap-code-bg": t.codeBg,
      "--tiptap-code-text": t.codeText,
      "--tiptap-padding": chatMode === "terminal"
        ? (isMobile ? "6px 10px" : "8px 10px")
        : (isMobile ? "8px 12px" : "10px 16px"),
      "--tiptap-font-family": chatMode === "terminal"
        ? "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace"
        : "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
      "--tiptap-font-size": chatMode === "terminal" ? "14px" : "15px",
      "--tiptap-line-height": chatMode === "terminal" ? "1.45" : "1.5",
    } as React.CSSProperties), [t.text, t.textDim, t.codeBg, t.codeText, isMobile, chatMode]);

    const selectItem = useCallback((item: CompletionItem) => {
      commandRef.current?.({ id: item.value, label: item.label });
    }, []);

    const selectCmdItem = useCallback((item: CompletionItem) => {
      if (!editor) return;
      const argMode = cmdArgModeRef.current;
      editor.commands.setContent(
        argMode
          ? buildCompletedSlashCommandText(argMode.commandId, item.value)
          : buildCompletedSlashCommandText(item.value),
        { emitUpdate: true },
      );
      editor.commands.focus("end");
      showCmdMenuRef.current = false;
      setShowCmdMenu(false);
      cmdArgModeRef.current = null;
    }, [editor]);

    return (
      <>
        <div
          ref={containerRef}
          className="tiptap-chat-input"
          style={cssVars}
          data-chat-mode={chatMode}
        >
          <EditorContent editor={editor} />
        </div>
        <AutocompleteMenu
          show={showMenu}
          items={filtered}
          activeIdx={activeIdx}
          menuPos={menuPos}
          onSelect={selectItem}
          onHover={(i) => { setActiveIdx(i); activeIdxRef.current = i; }}
          onClose={() => setShowMenu(false)}
          anchor="bottom"
          chatMode={chatMode}
        />
        <AutocompleteMenu
          show={showCmdMenu}
          items={cmdFiltered}
          activeIdx={cmdActiveIdx}
          menuPos={menuPos}
          onSelect={selectCmdItem}
          onHover={(i) => { setCmdActiveIdx(i); cmdActiveIdxRef.current = i; }}
          onClose={() => { setShowCmdMenu(false); showCmdMenuRef.current = false; }}
          anchor="bottom"
          chatMode={chatMode}
        />
      </>
    );
  },
);
