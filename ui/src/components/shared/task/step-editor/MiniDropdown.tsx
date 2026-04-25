import { SelectDropdown } from "../../SelectDropdown";

export function MiniDropdown({ value, options, onChange, className }: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <div className={className ?? ""}>
      <SelectDropdown
        value={value}
        options={options}
        onChange={(next) => onChange(next)}
        size="compact"
        popoverWidth="content"
        triggerClassName="min-h-[26px] border-surface-border/70 bg-surface-overlay/40 text-xs"
      />
    </div>
  );
}
