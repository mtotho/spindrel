# Notes

Notes are Markdown knowledge documents attached to a project or channel. They are meant for rough capture first, then structured refinement with the note assistant.

## Writing

Type directly in the editor. Notes autosave after a short pause, and the top-right status shows when the latest draft is saved. The document body is Markdown; use Preview when you want to read the formatted version.

Use normal editor selection for focused edits. If text is selected, magic edits target that selection. If nothing is selected, magic edits target the whole note.

## Magic Edit

`Clarify & Structure` is the default assistant action. It should preserve your meaning, organize the Markdown, and avoid inventing unsupported facts.

For a specific change, write the instruction in the magic edit box. The assistant applies the change to the editor draft, briefly highlights the changed text, and shows an undo action. It should ask a question only when the request is ambiguous enough that applying a change would be risky.

## Note Chat

Open note chat when the work needs conversation instead of a single edit. Note chat is pinned to the active note and loaded with the notes skill, so requests like "add this to the note" should operate on this Markdown document, not unrelated bot memory.

The model selector controls the model used for magic edits. Leave it on the default unless you need a specific model for a note.

## Knowledge Base

Each note is stored as a Markdown file in the knowledge base area with frontmatter for metadata such as title, tags, summary, timestamps, and note kind. Revisions are kept through the normal workspace version history, so recovery should come from undo first and version history when needed.

