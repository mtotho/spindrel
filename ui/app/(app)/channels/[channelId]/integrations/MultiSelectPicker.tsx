import { Check } from "lucide-react";

export function MultiSelectPicker({
  options,
  selected,
  onChange,
}: {
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const toggle = (value: string) => {
    if (selected.includes(value)) {
      onChange(selected.filter((v) => v !== value));
    } else {
      onChange([...selected, value]);
    }
  };

  return (
    <div className="flex flex-col gap-1.5">
      {options.map((opt) => {
        const isChecked = selected.includes(opt.value);
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => toggle(opt.value)}
            className="flex items-center gap-2 bg-transparent py-0.5 text-left transition-colors"
          >
            <div
              className={
                `flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors ` +
                (isChecked ? "border-accent bg-accent" : "border-surface-border bg-transparent")
              }
            >
              {isChecked && <Check size={10} className="text-white" strokeWidth={3} />}
            </div>
            <span className="text-[13px] leading-snug text-text">{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
