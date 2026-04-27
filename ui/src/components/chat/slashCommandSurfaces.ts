import type { SlashCommandId, SlashCommandSpec, SlashCommandSurface } from "@/src/types/api";

export type SlashCommandCapability =
  | "clear"
  | "new"
  | "scratch"
  | "model"
  | "theme"
  | "sessions"
  | "split"
  | "focus";

export interface ResolveSlashCommandSurfaceOptions {
  catalog: SlashCommandSpec[];
  surface: SlashCommandSurface;
  enabled: boolean;
  capabilities?: readonly SlashCommandCapability[];
}

export function resolveAvailableSlashCommandIds({
  catalog,
  surface,
  enabled,
  capabilities = [],
}: ResolveSlashCommandSurfaceOptions): SlashCommandId[] {
  if (!enabled) return [];
  const capabilitySet = new Set<SlashCommandId>(capabilities);
  return catalog
    .filter((command) => command.surfaces.includes(surface))
    .filter((command) => !command.local_only || capabilitySet.has(command.id))
    .map((command) => command.id);
}
