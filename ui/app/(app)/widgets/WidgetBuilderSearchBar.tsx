import { Search, X } from "lucide-react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  className?: string;
}

export function WidgetBuilderSearchBar({
  value,
  onChange,
  placeholder,
  className = "",
}: Props) {
  return (
    <div className={className}>
      <label className="flex items-center gap-2 rounded-md bg-input px-3 py-2">
        <Search size={13} className="text-text-dim" />
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 bg-transparent text-[12px] text-text placeholder-text-dim outline-none"
        />
        {value && (
          <button
            type="button"
            onClick={() => onChange("")}
            className="rounded-md p-0.5 text-text-dim hover:bg-surface-overlay"
            aria-label="Clear search"
          >
            <X size={11} />
          </button>
        )}
      </label>
    </div>
  );
}
