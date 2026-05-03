export type ProjectRailChildKey = "overview" | "runs" | "feed" | "git" | "files";

export interface ProjectRailContext {
  projectId: string;
  activeChild: ProjectRailChildKey;
}

const CHILD_KEYS = new Set<ProjectRailChildKey>(["overview", "runs", "feed", "git", "files"]);

export function projectRailContextForLocation(pathname: string, hash = ""): ProjectRailContext | null {
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] !== "admin" || parts[1] !== "projects") return null;
  const projectId = parts[2];
  if (!projectId || projectId === "blueprints") return null;
  if (parts[3] === "runs") return { projectId, activeChild: "runs" };

  const requested = decodeURIComponent(hash.replace(/^#/, "")).toLowerCase();
  if (CHILD_KEYS.has(requested as ProjectRailChildKey)) {
    return { projectId, activeChild: requested as ProjectRailChildKey };
  }
  return { projectId, activeChild: "overview" };
}
