import React, { useState, useRef, useCallback, useEffect, useLayoutEffect, forwardRef, useImperativeHandle, useMemo } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";
import MentionBase from "@tiptap/extension-mention";
import { Extension, InputRule } from "@tiptap/core";
import { Plugin, TextSelection } from "@tiptap/pm/state";
import { Markdown } from "tiptap-markdown";
import { useCompletions } from "../../api/hooks/useModels";
import { AutocompleteMenu, scoreMatch } from "../shared/LlmPrompt";
import { useThemeTokens } from "../../theme/tokens";
import type { CompletionItem } from "../../types/api";
import type { SuggestionProps, SuggestionKeyDownProps } from "@tiptap/suggestion";
import "./tiptap-input.css";

// Extend Mention with markdown serialization so getMarkdown() outputs @value
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
});

export interface TiptapChatInputProps {
  text: string;
  onTextChange: (markdown: string) => void;
  onSubmit: () => void;
  onImagePaste?: (files: File[]) => void;
  disabled?: boolean;
  autoFocus?: boolean;
  isMobile?: boolean;
  currentBotId?: string;
}

export interface TiptapChatInputHandle {
  focus: () => void;
  clear: () => void;
  getMarkdown: () => string;
}

export const TiptapChatInput = forwardRef<TiptapChatInputHandle, TiptapChatInputProps>(
  function TiptapChatInput({ text, onTextChange, onSubmit, onImagePaste, disabled, autoFocus, isMobile, currentBotId }, ref) {
    const t = useThemeTokens();
    const { data: completions } = useCompletions();
    const containerRef = useRef<HTMLDivElement>(null);

    // Stable refs for closure access (suggestion callbacks + extension shortcuts)
    const completionsRef = useRef(completions);
    completionsRef.current = completions;
    const currentBotIdRef = useRef(currentBotId);
    currentBotIdRef.current = currentBotId;
    const onSubmitRef = useRef(onSubmit);
    onSubmitRef.current = onSubmit;
    const onTextChangeRef = useRef(onTextChange);
    onTextChangeRef.current = onTextChange;
    const onImagePasteRef = useRef(onImagePaste);
    onImagePasteRef.current = onImagePaste;
    const initialTextRef = useRef(text);

    // Guard: suppress onTextChange during programmatic setContent (draft restore, clear)
    const suppressUpdateRef = useRef(false);

    // Autocomplete menu state
    const [showMenu, setShowMenu] = useState(false);
    const [menuPos, setMenuPos] = useState({ top: 0, left: 0, width: 0 });
    const [filtered, setFiltered] = useState<CompletionItem[]>([]);
    const [activeIdx, setActiveIdx] = useState(0);
    const filteredRef = useRef<CompletionItem[]>([]);
    const activeIdxRef = useRef(0);
    const commandRef = useRef<((props: { id: string; label: string }) => void) | null>(null);

    useEffect(() => { filteredRef.current = filtered; }, [filtered]);
    useEffect(() => { activeIdxRef.current = activeIdx; }, [activeIdx]);

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

    // Mention suggestion config — stable via refs
    const suggestion = useMemo(() => ({
      char: "@",
      items: ({ query }: { query: string }) => {
        const comps = completionsRef.current;
        if (!comps) return [];
        const excludeValue = currentBotIdRef.current ? `bot:${currentBotIdRef.current}` : "";
        return comps
          .filter((c: CompletionItem) => c.value !== excludeValue)
          .map((c: CompletionItem) => ({ c, s: scoreMatch(c.value, c.label, query) }))
          .filter((x: { s: number }) => x.s > 0)
          .sort((a: { s: number }, b: { s: number }) => b.s - a.s)
          .map((x: { c: CompletionItem }) => x.c)
          .slice(0, 10);
      },
      render: () => ({
        onStart: (props: SuggestionProps<CompletionItem>) => {
          commandRef.current = props.command as any;
          setFiltered(props.items);
          filteredRef.current = props.items;
          setActiveIdx(0);
          activeIdxRef.current = 0;
          updateMenuPos();
          setShowMenu(props.items.length > 0);
        },
        onUpdate: (props: SuggestionProps<CompletionItem>) => {
          commandRef.current = props.command as any;
          setFiltered(props.items);
          filteredRef.current = props.items;
          setActiveIdx(0);
          activeIdxRef.current = 0;
          updateMenuPos();
          setShowMenu(props.items.length > 0);
        },
        onExit: () => {
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
            // Enter outside code block → submit (code block Enter handled by raw plugin below)
            Enter: ({ editor: ed }) => {
              if (ed.isActive("codeBlock")) return false;
              onSubmitRef.current();
              return true;
            },
            Escape: ({ editor: ed }) => {
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
              return false;
            },
            Tab: ({ editor: ed }) => {
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
      Placeholder.configure({ placeholder: "Type a message..." }),
      Mention.configure({
        HTMLAttributes: { class: "mention" },
        renderText({ node }) {
          return `@${node.attrs.id}`;
        },
        suggestion,
      }),
    ], [suggestion]);

    const editor = useEditor({
      extensions,
      content: "",
      editable: !disabled,
      autofocus: autoFocus ? "end" : false,
      onUpdate: ({ editor: ed }) => {
        if (suppressUpdateRef.current) return;
        const md = (ed.storage as any).markdown.getMarkdown();
        onTextChangeRef.current(md);
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

    useImperativeHandle(ref, () => ({
      focus: () => editor?.commands.focus("end"),
      clear: () => {
        suppressUpdateRef.current = true;
        editor?.commands.clearContent(true);
        editor?.commands.unsetAllMarks();
        suppressUpdateRef.current = false;
      },
      getMarkdown: () => (editor?.storage as any)?.markdown?.getMarkdown() ?? "",
    }), [editor]);

    const cssVars = useMemo(() => ({
      "--tiptap-text": t.text,
      "--tiptap-text-dim": t.textDim,
      "--tiptap-code-bg": t.codeBg,
      "--tiptap-code-text": t.codeText,
      "--tiptap-padding": isMobile ? "8px 12px" : "10px 16px",
    } as React.CSSProperties), [t.text, t.textDim, t.codeBg, t.codeText, isMobile]);

    const selectItem = useCallback((item: CompletionItem) => {
      commandRef.current?.({ id: item.value, label: item.label });
    }, []);

    return (
      <>
        <div
          ref={containerRef}
          className="tiptap-chat-input"
          style={cssVars}
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
        />
      </>
    );
  },
);
