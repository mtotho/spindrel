# UI Components — Canonical Shared Controls

This guide is the component catalog for Spindrel UI work. `ui-design.md` owns visual principles; this file owns exact shared controls to use before creating local variants.

## Rule

Do not hand-roll dropdowns, prompt textareas, setting rows, action buttons, badges, or empty states when a shared component exists. If the shared component is missing a capability, extend it once and migrate callers.

## Selectors

Use `ui/src/components/shared/SelectDropdown.tsx` for custom dropdowns.

- Use for searchable lists, grouped lists, entity pickers, model/bot/channel/tool/workflow selectors, and any select that should not inherit browser-native styling.
- Default popover width is clamped for readability. Do not match a full-width settings row unless the list is genuinely short and static.
- `SelectInput` and model pickers must not open page-wide popovers just because their trigger sits in a full-width form row.
- Chrome is fixed: `rounded-md`, `bg-input` trigger, low-opacity selected rows, no `shadow-xl`, no filled blue trigger/action, no decorative border stack.
- Group options with `group` / `groupLabel`; search text with `searchText`; custom rows with `renderOption`.
- Keep native `<select>` only through `SelectInput` for tiny static choices. `SelectInput` delegates to `SelectDropdown` and enables search only when option count is high.

Domain wrappers that must use `SelectDropdown`:

- `LlmModelDropdown` for LLM and embedding model selection.
- `BotPicker` for bot/entity selection.
- `ChannelPicker` for channel/entity selection.
- `ToolSelector` for tool binding.
- `WorkflowSelector` for workflow binding.
- Prompt template insertion, task step controls, preset option pickers, pin scope bot selection, and schema enum/boolean fields should also route through `SelectDropdown`.

## Prompt Editors

Use `PromptEditor` from `ui/src/components/shared/LlmPrompt.tsx`. `LlmPrompt` is a compatibility alias and should not grow new behavior.

- Prompt areas must be comfortably editable by default: minimum height at least 160px, vertical resize, mono text, visible char/token estimate.
- Every prompt editor gets an `Expand` action that opens the fullscreen editor with the same autocomplete and generation behavior.
- Prompt autocomplete remains the `@` tag menu. Do not build a second completion menu.
- Generate actions are quiet text actions. No filled blue/green prompt buttons for routine generation or completion.
- Workspace-backed prompt editors should reuse the same sizing/action language even when they need Save/Cancel/Unlink controls.

## Date And Time

Use `DateTimePicker` and `TimePicker` from `ui/src/components/shared/DateTimePicker.tsx`.

- Do not use native `type="time"` or `datetime-local` controls in settings surfaces; browser chrome/icons are inconsistent and can fail dark mode.
- `TimePicker` is the canonical time-only control for schedules, quiet hours, and time windows.
- `DateTimePicker` is the canonical absolute date+time control for task starts and scheduled execution.
- Date/time pickers should stay low-chrome: muted trigger icon, `rounded-md`, no `shadow-xl`, no filled accent selected day, no browser-native picker icon.

## Settings Controls

Use `FormControls.tsx` and `SettingsControls.tsx`.

- `Section`: title/description/action only; no section card chrome.
- `FormRow`: label, control, optional description.
- `ActionButton`: primary is transparent accent text; secondary is muted text; danger is text-danger. Filled accent is reserved for rare final confirmation.
- `SettingsControlRow`: logical row item with low tonal fill. Add borders only for expanded inline forms.
- `EmptyState`: dashed low-chrome placeholder.
- `StatusBadge`, `InfoBanner`, and `SaveStatusPill`: semantic state only, not decoration.
- `QuietPill`: low-emphasis metadata tags inside dense rows. Use this for archived-section tags, compact row labels, and other metadata that should not compete with the row title.

## Review Checklist

- A dropdown or selector imports `SelectDropdown` or an approved wrapper.
- A prompt imports `PromptEditor` or `LlmPrompt`.
- A date/time control imports `DateTimePicker` or `TimePicker`; no native browser date/time inputs in settings.
- Widget, task, and prompt-template configuration surfaces do not ship native `<select>` or local portal dropdowns unless they are documented specialized controls.
- Routine settings actions are not filled blue buttons.
- Dense-row metadata uses `QuietPill`; reserve `StatusBadge` for actual state.
- Popovers are not page-wide and do not use shadow stacks.
- Knowledge/help copy is typography-led; do not turn every explanatory sentence into a faded panel.
