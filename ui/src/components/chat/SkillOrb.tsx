/**
 * SkillOrb — static indicator of how many skills are currently in the LLM's
 * context on this message (from prior `get_skill()` calls still sitting in
 * conversation history). Sits in the header row alongside the timestamp and
 * other message-level badges. Hover or keyboard-focus opens a small popover
 * with the list of skill names.
 *
 * Static, no animation — previous pulsing-dot version read as a "typing"
 * indicator.
 *
 * Data source: `message.metadata.active_skills` piped from
 * `app/agent/context_assembly.py` via loop → turn_worker → sessions.persist_turn.
 * `auto_injected_skills` is merged for back-compat on older messages.
 */

import { useState, useId } from "react";
import { Sparkles } from "lucide-react";
import type { ThemeTokens } from "../../theme/tokens";

export type ActiveSkillLike = {
  skill_id?: string;
  skillId?: string;
  skill_name?: string;
  skillName?: string;
  similarity?: number;
};

function normalize(skills: ActiveSkillLike[]): { id: string; name: string }[] {
  const seen = new Set<string>();
  const out: { id: string; name: string }[] = [];
  for (const s of skills) {
    const id = s.skill_id ?? s.skillId ?? "";
    const name = s.skill_name ?? s.skillName ?? id ?? "skill";
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, name });
  }
  return out;
}

export function SkillOrb({
  active,
  autoInjected,
  t,
}: {
  active: ActiveSkillLike[];
  autoInjected?: ActiveSkillLike[];
  t: ThemeTokens;
}) {
  const [open, setOpen] = useState(false);
  const popoverId = useId();

  const skills = normalize([...(active ?? []), ...(autoInjected ?? [])]);
  if (skills.length === 0) return null;
  const count = skills.length;

  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <span
        role="button"
        tabIndex={0}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={popoverId}
        aria-label={`${count} ${count === 1 ? "skill" : "skills"} in context`}
        className="inline-flex flex-row items-center gap-1 rounded-full cursor-default outline-none focus-visible:ring-1"
        style={{
          padding: "1px 7px",
          backgroundColor: t.purpleSubtle,
          border: `1px solid ${t.purpleBorder}`,
          lineHeight: 1.4,
        }}
      >
        <Sparkles size={9} style={{ color: t.purple, flexShrink: 0 }} strokeWidth={2.5} />
        <span
          className="text-[10px] font-semibold"
          style={{ color: t.purple, letterSpacing: 0.3 }}
        >
          {count}
        </span>
      </span>

      {open && (
        <span
          id={popoverId}
          role="dialog"
          className="absolute z-20 top-full left-0 mt-1 rounded-lg border shadow-lg flex flex-col"
          style={{
            padding: "6px 8px",
            minWidth: 180,
            maxWidth: 320,
            backgroundColor: t.surfaceRaised,
            borderColor: t.surfaceBorder,
            gap: 4,
          }}
        >
          <span
            className="text-[9px] font-semibold uppercase tracking-wider"
            style={{ color: t.textDim, marginBottom: 2 }}
          >
            skills in context
          </span>
          {skills.map((s) => (
            <span
              key={s.id}
              className="inline-flex items-center gap-1.5"
              style={{ lineHeight: 1.3 }}
              title={s.id}
            >
              <span
                style={{
                  width: 4,
                  height: 4,
                  borderRadius: "50%",
                  backgroundColor: t.purple,
                  flexShrink: 0,
                }}
              />
              <span
                className="text-[11px] font-medium overflow-hidden text-ellipsis whitespace-nowrap"
                style={{ color: t.textMuted }}
              >
                {s.name}
              </span>
            </span>
          ))}
        </span>
      )}
    </span>
  );
}
