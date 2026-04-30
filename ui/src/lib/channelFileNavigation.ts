export const CHANNEL_FILES_PATH_PARAM = "files_path";
export const CHANNEL_OPEN_FILE_PARAM = "open_file";
export const CHANNEL_FILE_LINK_OPEN_EVENT = "spindrel:open-channel-file";

export interface ChannelFileLinkOpenDetail {
  channelId: string;
  path: string;
  split: boolean;
}

function trimSlashes(value: string): string {
  return value.replace(/^\/+/, "").replace(/\/+$/, "");
}

export function normalizeWorkspaceNavigationPath(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null;
  if (value.trim() == ".") return "";
  const trimmed = trimSlashes(value.trim());
  return trimmed || null;
}

export function defaultChannelBrowsePath(channelId: string): string {
  return `channels/${channelId}`;
}

export interface ChannelFileViewerScope {
  kind: "channel" | "workspace";
  path: string;
}

const WORKSPACE_SCOPE_PREFIXES = ["bots/", "common/", "projects/", "workspaces/"];
const APP_ROUTE_PREFIXES = ["/admin/", "/channels/", "/settings", "/widgets/", "/tasks/"];
const EXTERNAL_SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;
const FILE_LIKE_BASENAME_RE = /(^|\/)[^/?#]+\.[A-Za-z0-9][A-Za-z0-9._-]*(?:$|[?#])/;

export function resolveChannelFileViewerScope(
  channelId: string,
  filePath: string,
): ChannelFileViewerScope {
  const normalized = normalizeWorkspaceNavigationPath(filePath) ?? "";
  const channelPrefix = `${defaultChannelBrowsePath(channelId)}/`;
  if (normalized.startsWith(channelPrefix)) {
    return { kind: "channel", path: normalized.slice(channelPrefix.length) };
  }
  if (
    normalized.startsWith("channels/")
    || WORKSPACE_SCOPE_PREFIXES.some((prefix) => normalized.startsWith(prefix))
  ) {
    return { kind: "workspace", path: normalized };
  }
  return { kind: "channel", path: normalized };
}

export function resolveChannelLinkedFilePath(
  href: string | null | undefined,
): string | null {
  if (typeof href !== "string") return null;
  const raw = href.trim().replace(/^['"]|['"]$/g, "");
  if (!raw || raw.startsWith("#") || APP_ROUTE_PREFIXES.some((prefix) => raw.startsWith(prefix))) {
    return null;
  }
  if (EXTERNAL_SCHEME_RE.test(raw)) return null;
  const pathOnly = raw.split("#", 1)[0]?.split("?", 1)[0] ?? "";
  const normalized = normalizeWorkspaceNavigationPath(decodeURIComponent(pathOnly));
  if (!normalized) return null;
  if (!normalized.includes("/") && !FILE_LIKE_BASENAME_RE.test(normalized)) return null;
  return normalized.replace(/^\.\//, "");
}

export function resolveToolTargetFilePath(
  target: string | null | undefined,
): string | null {
  if (typeof target !== "string") return null;
  const raw = target.trim().replace(/^['"]|['"]$/g, "");
  if (
    !raw
    || raw.startsWith("/")
    || raw.startsWith("~/")
    || /^[A-Za-z]:[\\/]/.test(raw)
    || /\s/.test(raw)
  ) {
    return null;
  }
  return resolveChannelLinkedFilePath(raw);
}

export function directoryForWorkspaceFile(path: string): string {
  const normalized = normalizeWorkspaceNavigationPath(path);
  if (!normalized) return "";
  const slash = normalized.lastIndexOf("/");
  return slash > 0 ? normalized.slice(0, slash) : "";
}

export interface ChannelFileIntent {
  directoryPath: string;
  openFile: string | null;
}

export function readChannelFileIntent(
  searchParams: URLSearchParams,
  channelId: string,
): ChannelFileIntent | null {
  const rawDirectoryPath = searchParams.get(CHANNEL_FILES_PATH_PARAM);
  const directoryPath = normalizeWorkspaceNavigationPath(
    rawDirectoryPath,
  );
  const openFile = normalizeWorkspaceNavigationPath(
    searchParams.get(CHANNEL_OPEN_FILE_PARAM),
  );
  if (!directoryPath && !openFile) return null;
  const derivedDirectory = openFile ? directoryForWorkspaceFile(openFile) : null;
  return {
    directoryPath:
      rawDirectoryPath != null
        ? (directoryPath ?? "")
        : (openFile != null
            ? (derivedDirectory ?? "")
            : defaultChannelBrowsePath(channelId)),
    openFile,
  };
}

export interface ChannelFileHrefTarget {
  channelId: string;
  sessionId?: string | null;
  scratch?: boolean;
  directoryPath?: string | null;
  openFile?: string | null;
}

export function buildChannelFileHref(target: ChannelFileHrefTarget): string {
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
