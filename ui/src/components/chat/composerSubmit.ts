import type { SlashCommandId, SlashCommandSpec, SlashCommandSurface } from "../../types/api";
import { detectMissingSlashArgs, resolveSlashCommand } from "./slashCommands.js";

export type ComposerSubmitIntent<TFile = unknown> =
  | { kind: "idle" }
  | { kind: "blocked"; reason: string }
  | { kind: "slash"; id: SlashCommandId; args: string[]; argsText: string }
  | { kind: "missing_slash_args"; id: SlashCommandId; missing: string[] }
  | { kind: "send"; message: string; files?: TFile[] };

export function resolveComposerSubmitIntent<TFile = unknown>({
  rawMessage,
  pendingFiles,
  disabled,
  sendDisabledReason,
  slashSurface,
  slashCatalog,
  availableSlashCommands,
}: {
  rawMessage: string;
  pendingFiles: TFile[];
  disabled?: boolean;
  sendDisabledReason?: string | null;
  slashSurface: SlashCommandSurface;
  slashCatalog: SlashCommandSpec[];
  availableSlashCommands?: SlashCommandId[];
}): ComposerSubmitIntent<TFile> {
  const message = rawMessage.trim();
  const hasFiles = pendingFiles.length > 0;
  if ((!message && !hasFiles) || disabled) return { kind: "idle" };
  if (sendDisabledReason) return { kind: "blocked", reason: sendDisabledReason };

  if (!hasFiles) {
    const slashCommand = resolveSlashCommand(
      message,
      slashSurface,
      slashCatalog,
      availableSlashCommands,
    );
    if (slashCommand) {
      return {
        kind: "slash",
        id: slashCommand.id,
        args: slashCommand.args,
        argsText: slashCommand.argsText,
      };
    }

    const missing = detectMissingSlashArgs(
      message,
      slashSurface,
      slashCatalog,
      availableSlashCommands,
    );
    if (missing) {
      return { kind: "missing_slash_args", id: missing.id, missing: missing.missing };
    }
  }

  return { kind: "send", message, files: hasFiles ? pendingFiles : undefined };
}
