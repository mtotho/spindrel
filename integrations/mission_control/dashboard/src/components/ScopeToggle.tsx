/** Fleet / Personal scope toggle — reads from ScopeContext. */
import { useScope } from "../lib/ScopeContext";

export default function ScopeToggle() {
  const { scope, setScope } = useScope();
  return (
    <div className="flex gap-1">
      {[
        { value: undefined, label: "Fleet" },
        { value: "personal" as const, label: "Personal" },
      ].map((opt) => (
        <button
          key={opt.label}
          onClick={() => setScope(opt.value)}
          className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
            scope === opt.value
              ? "border-accent bg-accent text-white"
              : "border-surface-3 text-gray-400 hover:text-gray-200"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
