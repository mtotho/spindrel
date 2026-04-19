// Predictive parser for @skill: tags in composer text.
// Mirrors the prefix-form half of the server-side regex in app/agent/tags.py:25.
// Unprefixed @name lookups (which the server resolves against bot_skills/tools/bots)
// are deliberately not handled — the UI doesn't have the resolution context, and
// the count catches up once the next assistant message tags `active_skills`.

const SKILL_TAG_RE = /(?<![<\w@])@skill:([A-Za-z_][\w\-./]*)/g;

export function parseSkillTags(text: string): string[] {
  if (!text) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of text.matchAll(SKILL_TAG_RE)) {
    const id = m[1];
    if (id && !seen.has(id)) {
      seen.add(id);
      out.push(id);
    }
  }
  return out;
}
