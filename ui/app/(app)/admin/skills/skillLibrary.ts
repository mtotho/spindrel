import yaml from "js-yaml";
import type { SkillItem } from "@/src/api/hooks/useSkills";

export type SkillSourceBucket = "core" | "integration" | "bot" | "manual";

export interface SkillFrontmatterAnalysis {
  frontmatter: Record<string, unknown>;
  frontmatterRaw: string;
  body: string;
  parseError: string | null;
  warnings: string[];
}

export interface SkillLibraryEntry {
  skill: SkillItem;
  analysis: SkillFrontmatterAnalysis;
  children: SkillLibraryEntry[];
}

export interface SkillLibraryGroup {
  key: string;
  label: string;
  bucket: SkillSourceBucket;
  entries: SkillLibraryEntry[];
  count: number;
}

const REQUIRED_FRONTMATTER = ["name", "description", "triggers", "category"] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

export function splitSkillContent(content: string): SkillFrontmatterAnalysis {
  const match = content.match(/^---\s*\n([\s\S]*?)\n---\s*(?:\n|$)([\s\S]*)$/);
  if (!match) {
    return {
      frontmatter: {},
      frontmatterRaw: "",
      body: content,
      parseError: null,
      warnings: REQUIRED_FRONTMATTER.map((field) => `Missing ${field}`),
    };
  }

  const frontmatterRaw = match[1] ?? "";
  let frontmatter: Record<string, unknown> = {};
  let parseError: string | null = null;
  try {
    const parsed = yaml.load(frontmatterRaw);
    frontmatter = isRecord(parsed) ? parsed : {};
  } catch (err) {
    parseError = err instanceof Error ? err.message : "Frontmatter could not be parsed";
  }

  const warnings = REQUIRED_FRONTMATTER.flatMap((field) => {
    const value = frontmatter[field];
    const missingArray = Array.isArray(value) && value.length === 0;
    if (value == null || value === "" || missingArray) return [`Missing ${field}`];
    return [];
  });
  if (parseError) warnings.unshift("Invalid frontmatter");

  return {
    frontmatter,
    frontmatterRaw,
    body: match[2] ?? "",
    parseError,
    warnings,
  };
}

export function analyzeSkill(skill: SkillItem): SkillFrontmatterAnalysis {
  const analysis = splitSkillContent(skill.content || "");
  const warnings = new Set(analysis.warnings);
  if (!skill.name?.trim()) warnings.add("Missing name");
  if (!skill.description?.trim() && !isNonEmptyString(analysis.frontmatter.description)) {
    warnings.add("Missing description");
  }
  if (!skill.category?.trim() && !isNonEmptyString(analysis.frontmatter.category)) {
    warnings.add("Missing category");
  }
  if (!skill.triggers?.length && !isNonEmptyArray(analysis.frontmatter.triggers)) {
    warnings.add("Missing triggers");
  }
  return { ...analysis, warnings: Array.from(warnings) };
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isNonEmptyArray(value: unknown): value is unknown[] {
  return Array.isArray(value) && value.length > 0;
}

export function skillSourceBucket(skill: SkillItem): SkillSourceBucket {
  if (skill.source_type === "integration") return "integration";
  if (skill.source_type === "tool") return "bot";
  if (skill.source_type === "manual") return "manual";
  return "core";
}

export function skillSourceLabel(skill: SkillItem): string {
  const bucket = skillSourceBucket(skill);
  if (bucket === "core") return "Core file";
  if (bucket === "manual") return "Manual";
  if (bucket === "bot") return skill.bot_id ? `Bot ${skill.bot_id}` : "Bot-authored";
  return integrationName(skill);
}

export function integrationName(skill: SkillItem): string {
  const raw = skill.id.match(/^integrations\/([^/]+)/)?.[1] ?? skill.source_path?.match(/integrations\/([^/]+)/)?.[1] ?? "Integration";
  const special: Record<string, string> = { github: "GitHub", arr: "ARR" };
  if (special[raw]) return special[raw];
  return raw.replace(/[_-]+/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function buildSkillLibraryGroups(skills: SkillItem[]): SkillLibraryGroup[] {
  const byId = new Map(skills.map((skill) => [skill.id, skill]));
  const entries = new Map<string, SkillLibraryEntry>();
  for (const skill of skills) {
    entries.set(skill.id, { skill, analysis: analyzeSkill(skill), children: [] });
  }

  const roots: SkillLibraryEntry[] = [];
  for (const entry of entries.values()) {
    const parentId = entry.skill.parent_skill_id || null;
    const parent = parentId ? entries.get(parentId) : null;
    if (parent && parentId != null && byId.has(parentId)) {
      parent.children.push(entry);
    } else {
      roots.push(entry);
    }
  }

  const sortedRoots = roots.sort(sortEntries);
  for (const entry of entries.values()) entry.children.sort(sortEntries);

  const groups = new Map<string, SkillLibraryGroup>();
  for (const entry of sortedRoots) {
    const bucket = skillSourceBucket(entry.skill);
    const key = bucket === "integration" ? `integration:${integrationName(entry.skill)}` : bucket;
    const label =
      bucket === "core" ? "Core Skills" :
      bucket === "bot" ? "Bot-Authored Skills" :
      bucket === "manual" ? "Manual Skills" :
      integrationName(entry.skill);
    const group = groups.get(key) ?? { key, label, bucket, entries: [], count: 0 };
    group.entries.push(entry);
    group.count += countEntry(entry);
    groups.set(key, group);
  }

  return Array.from(groups.values()).sort((a, b) => {
    const order: Record<SkillSourceBucket, number> = { core: 0, integration: 1, bot: 2, manual: 3 };
    return order[a.bucket] - order[b.bucket] || a.label.localeCompare(b.label);
  });
}

export function filterSkillEntry(entry: SkillLibraryEntry, term: string): SkillLibraryEntry | null {
  const query = term.trim().toLowerCase();
  if (!query) return entry;
  const childMatches = entry.children.flatMap((child) => {
    const next = filterSkillEntry(child, query);
    return next ? [next] : [];
  });
  if (entryMatches(entry, query) || childMatches.length > 0) {
    return { ...entry, children: childMatches };
  }
  return null;
}

export function countEntry(entry: SkillLibraryEntry): number {
  return 1 + entry.children.reduce((sum, child) => sum + countEntry(child), 0);
}

export function childCount(entry: SkillLibraryEntry): number {
  return entry.children.reduce((sum, child) => sum + countEntry(child), 0);
}

function entryMatches(entry: SkillLibraryEntry, query: string): boolean {
  const skill = entry.skill;
  return [
    skill.id,
    skill.name,
    skill.description,
    skill.category,
    skill.source_type,
    skill.source_path,
    skillSourceLabel(skill),
    ...(skill.triggers ?? []),
  ].filter(Boolean).join(" ").toLowerCase().includes(query);
}

function sortEntries(a: SkillLibraryEntry, b: SkillLibraryEntry): number {
  const aRoot = a.skill.has_children || a.skill.skill_layout === "folder_root";
  const bRoot = b.skill.has_children || b.skill.skill_layout === "folder_root";
  if (aRoot !== bRoot) return aRoot ? -1 : 1;
  return a.skill.name.localeCompare(b.skill.name) || a.skill.id.localeCompare(b.skill.id);
}
