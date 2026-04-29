export const CHANNEL_FILES_PATH_PARAM = "files_path";
export const CHANNEL_OPEN_FILE_PARAM = "open_file";
function trimSlashes(value) {
    return value.replace(/^\/+/, "").replace(/\/+$/, "");
}
export function normalizeWorkspaceNavigationPath(value) {
    if (typeof value !== "string")
        return null;
    if (value.trim() == ".")
        return "";
    const trimmed = trimSlashes(value.trim());
    return trimmed || null;
}
export function defaultChannelBrowsePath(channelId) {
    return `channels/${channelId}`;
}
const WORKSPACE_SCOPE_PREFIXES = ["bots/", "common/", "projects/", "workspaces/"];
export function resolveChannelFileViewerScope(channelId, filePath) {
    const normalized = normalizeWorkspaceNavigationPath(filePath) ?? "";
    const channelPrefix = `${defaultChannelBrowsePath(channelId)}/`;
    if (normalized.startsWith(channelPrefix)) {
        return { kind: "channel", path: normalized.slice(channelPrefix.length) };
    }
    if (normalized.startsWith("channels/")
        || WORKSPACE_SCOPE_PREFIXES.some((prefix) => normalized.startsWith(prefix))) {
        return { kind: "workspace", path: normalized };
    }
    return { kind: "channel", path: normalized };
}
export function directoryForWorkspaceFile(path) {
    const normalized = normalizeWorkspaceNavigationPath(path);
    if (!normalized)
        return "";
    const slash = normalized.lastIndexOf("/");
    return slash > 0 ? normalized.slice(0, slash) : "";
}
export function readChannelFileIntent(searchParams, channelId) {
    const rawDirectoryPath = searchParams.get(CHANNEL_FILES_PATH_PARAM);
    const directoryPath = normalizeWorkspaceNavigationPath(rawDirectoryPath);
    const openFile = normalizeWorkspaceNavigationPath(searchParams.get(CHANNEL_OPEN_FILE_PARAM));
    if (!directoryPath && !openFile)
        return null;
    const derivedDirectory = openFile ? directoryForWorkspaceFile(openFile) : null;
    return {
        directoryPath: rawDirectoryPath != null
            ? (directoryPath ?? "")
            : (openFile != null
                ? (derivedDirectory ?? "")
                : defaultChannelBrowsePath(channelId)),
        openFile,
    };
}
export function buildChannelFileHref(target) {
    const base = target.sessionId
        ? `/channels/${target.channelId}/session/${target.sessionId}`
        : `/channels/${target.channelId}`;
    const searchParams = new URLSearchParams();
    if (target.sessionId && target.scratch) {
        searchParams.set("scratch", "true");
    }
    const rawDirectoryPath = target.directoryPath;
    const directoryPath = normalizeWorkspaceNavigationPath(rawDirectoryPath);
    if (rawDirectoryPath === "/" || rawDirectoryPath === "." || directoryPath != null) {
        searchParams.set(CHANNEL_FILES_PATH_PARAM, directoryPath || ".");
    }
    const openFile = normalizeWorkspaceNavigationPath(target.openFile);
    if (openFile) {
        searchParams.set(CHANNEL_OPEN_FILE_PARAM, openFile);
    }
    const suffix = searchParams.toString();
    return suffix ? `${base}?${suffix}` : base;
}
