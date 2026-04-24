import type {
  CompletionItem,
  ModelGroup,
  SlashCommandArgSource,
} from "../../types/api";

/** Produce completion items for a single slash-command arg.
 *
 * Pure function so callers can feed pre-fetched data (models, etc.) in from
 * React hooks they already call at component scope. Keeps this module free
 * of hook dependencies and trivially testable.
 */
export function resolveArgSourceItems(
  source: SlashCommandArgSource,
  enumValues: string[] | null | undefined,
  modelGroups: ModelGroup[] | undefined,
): CompletionItem[] {
  if (source === "enum") {
    return (enumValues ?? []).map((value) => ({
      value,
      label: value,
    }));
  }
  if (source === "model") {
    if (!modelGroups) return [];
    return modelGroups.flatMap((group) =>
      group.models.map((model) => ({
        value: model.id,
        label: model.id,
        description:
          model.display && model.display !== model.id
            ? `${group.provider_name} — ${model.display}`
            : group.provider_name,
      })),
    );
  }
  // free_text: no completions; the user types freely
  return [];
}

/** Filter completion items by a prefix query, preserving order.
 *
 * We use case-insensitive substring match rather than strict startsWith so
 * partial matches (e.g. "opus" in "claude-opus-4-7") still surface.
 */
export function filterArgItems(
  items: CompletionItem[],
  query: string,
  limit = 20,
): CompletionItem[] {
  const q = query.trim().toLowerCase();
  if (!q) return items.slice(0, limit);
  return items
    .filter(
      (item) =>
        item.value.toLowerCase().includes(q) ||
        item.label.toLowerCase().includes(q),
    )
    .slice(0, limit);
}

/** Look up the provider id for a model by id, first match wins.
 *
 * `/model <id>` dispatches via the client-side handler which needs both
 * `(modelId, providerId)` to call `setModelOverride`. This mirrors how
 * `LlmModelDropdown` resolves the pair.
 */
export function resolveProviderForModel(
  modelId: string,
  modelGroups: ModelGroup[] | undefined,
): string | null {
  if (!modelGroups) return null;
  for (const group of modelGroups) {
    if (group.models.some((m) => m.id === modelId)) {
      return group.provider_id ?? null;
    }
  }
  return null;
}
