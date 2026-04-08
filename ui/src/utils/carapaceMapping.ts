import type { Carapace } from "../types/api";

export interface SkillCarapaceInfo {
  carapaceId: string;
  carapaceName: string;
  mode: string;
}

export interface ToolCarapaceInfo {
  carapaceId: string;
  carapaceName: string;
}

/**
 * Build a map of skill ID → contributing carapace, walking includes.
 */
export function buildSkillCarapaceMap(
  allCarapaces: Carapace[],
  activeCarapaceIds: string[],
): Map<string, SkillCarapaceInfo> {
  const map = new Map<string, SkillCarapaceInfo>();
  const carapaceById = new Map(allCarapaces.map((c) => [c.id, c]));
  const visited = new Set<string>();

  function walk(id: string, rootId: string, rootName: string) {
    const key = `${rootId}:${id}`;
    if (visited.has(key)) return;
    visited.add(key);
    const c = carapaceById.get(id);
    if (!c) return;
    for (const s of c.skills) {
      if (!map.has(s.id)) {
        map.set(s.id, { carapaceId: rootId, carapaceName: rootName, mode: s.mode || "on_demand" });
      }
    }
    for (const inc of c.includes) {
      walk(inc, rootId, rootName);
    }
  }

  for (const cId of activeCarapaceIds) {
    const c = carapaceById.get(cId);
    if (c) walk(cId, cId, c.name);
  }
  return map;
}

/**
 * Build a map of tool name → contributing carapace, walking includes.
 */
export function buildToolCarapaceMap(
  allCarapaces: Carapace[],
  activeCarapaceIds: string[],
): Map<string, ToolCarapaceInfo> {
  const map = new Map<string, ToolCarapaceInfo>();
  const carapaceById = new Map(allCarapaces.map((c) => [c.id, c]));
  const visited = new Set<string>();

  function walk(id: string, rootId: string, rootName: string) {
    const key = `${rootId}:${id}`;
    if (visited.has(key)) return;
    visited.add(key);
    const c = carapaceById.get(id);
    if (!c) return;
    for (const t of [...c.local_tools, ...c.mcp_tools, ...c.pinned_tools]) {
      if (!map.has(t)) {
        map.set(t, { carapaceId: rootId, carapaceName: rootName });
      }
    }
    for (const inc of c.includes) {
      walk(inc, rootId, rootName);
    }
  }

  for (const cId of activeCarapaceIds) {
    const c = carapaceById.get(cId);
    if (c) walk(cId, cId, c.name);
  }
  return map;
}
