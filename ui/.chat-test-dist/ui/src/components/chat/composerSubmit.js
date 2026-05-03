import { detectMissingSlashArgs, resolveSlashCommand } from "./slashCommands.js";
export function resolveComposerSubmitIntent({ rawMessage, pendingFiles, disabled, sendDisabledReason, slashSurface, slashCatalog, availableSlashCommands, }) {
    const message = rawMessage.trim();
    const hasFiles = pendingFiles.length > 0;
    if ((!message && !hasFiles) || disabled)
        return { kind: "idle" };
    if (sendDisabledReason)
        return { kind: "blocked", reason: sendDisabledReason };
    if (!hasFiles) {
        const slashCommand = resolveSlashCommand(message, slashSurface, slashCatalog, availableSlashCommands);
        if (slashCommand) {
            const spec = slashCatalog.find((cmd) => cmd.id === slashCommand.id);
            if (spec?.runtime_command_interaction_kind === "native_session") {
                return { kind: "send", message, files: undefined };
            }
            return {
                kind: "slash",
                id: slashCommand.id,
                args: slashCommand.args,
                argsText: slashCommand.argsText,
            };
        }
        const missing = detectMissingSlashArgs(message, slashSurface, slashCatalog, availableSlashCommands);
        if (missing) {
            return { kind: "missing_slash_args", id: missing.id, missing: missing.missing };
        }
    }
    return { kind: "send", message, files: hasFiles ? pendingFiles : undefined };
}
