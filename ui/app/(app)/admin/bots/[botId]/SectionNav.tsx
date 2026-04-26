import { ChevronDown } from "lucide-react";
import { SelectInput } from "@/src/components/shared/FormControls";
import { SettingsControlRow } from "@/src/components/shared/SettingsControls";
import { BOT_GROUPS, type BotGroupKey } from "./constants";

export function SectionNav({
  active,
  onSelect,
  filter,
  matchingSections,
  isMobile,
  visibleGroups,
}: {
  active: BotGroupKey;
  onSelect: (k: BotGroupKey) => void;
  filter: string;
  matchingSections: Set<BotGroupKey>;
  isMobile: boolean;
  visibleGroups?: readonly BotGroupKey[];
}) {
  const groups = visibleGroups
    ? BOT_GROUPS.filter((g) => visibleGroups.includes(g.key))
    : BOT_GROUPS;

  if (isMobile) {
    return (
      <div className="border-b border-surface-raised/60 bg-surface px-4 py-2">
        <SelectInput
          value={active}
          onChange={(value) => onSelect(value as BotGroupKey)}
          options={groups.map((group) => ({ label: group.label, value: group.key }))}
        />
      </div>
    );
  }

  return (
    <aside className="w-[190px] shrink-0 overflow-y-auto px-3 py-4">
      <div className="flex flex-col gap-1">
        {groups.map((group) => {
          const dimmed = !!filter && !matchingSections.has(group.key);
          return (
            <SettingsControlRow
              key={group.key}
              title={group.label}
              active={active === group.key}
              disabled={dimmed}
              compact
              onClick={() => onSelect(group.key)}
              action={active === group.key ? <ChevronDown size={12} className="text-accent" /> : undefined}
              className="bg-transparent"
            />
          );
        })}
      </div>
    </aside>
  );
}
