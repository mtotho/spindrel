/**
 * SkillOrb — ambient indicator showing which skills are currently in the LLM's
 * context on this message. A small breathing purple dot by default; hover or
 * keyboard-focus reveals a horizontal popover with one pill per active skill.
 *
 * Data source: `message.metadata.active_skills` (skills fetched via prior
 * `get_skill()` calls still sitting in conversation history) — computed in
 * `app/agent/context_assembly.py` and piped through loop → turn_worker →
 * sessions.persist_turn.
 *
 * For back-compat with older messages, `auto_injected_skills` is merged in by
 * skill_id if provided.
 */

import { useState, useId } from "react";
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
  const dotCount = count <= 3 ? count : 1;
  const showSuperscript = count > 3;

  return (
    <span
      className="relative inline-flex items-center align-middle"
      style={{ marginLeft: 4 }}
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
        className="inline-flex items-center gap-[2px] cursor-default outline-none focus-visible:ring-2 focus-visible:ring-offset-1 rounded-full"
        style={{
          padding: "2px 3px",
        }}
      >
        {Array.from({ length: dotCount }).map((_, i) => (
          <span
            key={i}
            className="skill-orb-dot inline-block rounded-full"
            style={{
              width: 6,
              height: 6,
              backgroundColor: t.purple,
              animation: "skillOrbPulse 2.2s ease-in-out infinite",
              animationDelay: `${i * 0.25}s`,
            }}
          />
        ))}
        {showSuperscript && (
          <sup
            className="text-[9px] font-semibold leading-none"
            style={{ color: t.purple, marginLeft: 2 }}
          >
            {count}
          </sup>
        )}
      </span>

      {open && (
        <span
          id={popoverId}
          role="dialog"
          className="absolute z-20 top-full left-0 mt-1 rounded-lg border shadow-lg flex flex-row flex-wrap gap-1"
          style={{
            padding: "4px 6px",
            minWidth: 140,
            maxWidth: 360,
            backgroundColor: t.surfaceRaised,
            borderColor: t.surfaceBorder,
          }}
        >
          <span
            className="text-[9px] font-semibold uppercase tracking-wider self-center"
            style={{ color: t.textDim, marginRight: 4 }}
          >
            in context
          </span>
          {skills.map((s) => (
            <span
              key={s.id}
              className="inline-flex items-center gap-1 rounded-full"
              style={{
                padding: "1px 7px 1px 5px",
                backgroundColor: t.purpleSubtle,
                border: `1px solid ${t.purpleBorder}`,
              }}
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
              <span className="text-[10px] font-medium" style={{ color: t.textMuted }}>
                {s.name}
              </span>
            </span>
          ))}
        </span>
      )}

      <style>{`
        @keyframes skillOrbPulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 0.85; }
        }
        @media (prefers-reduced-motion: reduce) {
          .skill-orb-dot { animation: none !important; opacity: 0.6 !important; }
        }
      `}</style>
    </span>
  );
}
