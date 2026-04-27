export function resolveAvailableSlashCommandIds({ catalog, surface, enabled, capabilities = [], }) {
    if (!enabled)
        return [];
    const capabilitySet = new Set(capabilities);
    return catalog
        .filter((command) => command.surfaces.includes(surface))
        .filter((command) => !command.local_only || capabilitySet.has(command.id))
        .map((command) => command.id);
}
