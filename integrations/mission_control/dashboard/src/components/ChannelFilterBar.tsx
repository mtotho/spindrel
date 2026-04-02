/**
 * Reusable channel filter pills with colored dots.
 * Renders pills for ≤5 channels, dropdown for >5.
 */
import { channelColor } from "../lib/colors";

interface Channel {
  id: string;
  name: string | null;
}

interface ChannelFilterBarProps {
  channels: Channel[];
  value: string | null;
  onChange: (channelId: string | null) => void;
}

export default function ChannelFilterBar({ channels, value, onChange }: ChannelFilterBarProps) {
  if (channels.length <= 1) return null;

  // Dropdown mode for many channels
  if (channels.length > 5) {
    return (
      <select
        value={value || ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="bg-surface-1 border border-surface-3 rounded-md px-2.5 py-1 text-xs text-content-muted"
      >
        <option value="">All channels</option>
        {channels.map((ch) => (
          <option key={ch.id} value={ch.id}>
            {ch.name || ch.id.slice(0, 8)}
          </option>
        ))}
      </select>
    );
  }

  // Pills mode
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => onChange(null)}
        className={`px-2.5 py-1 text-xs rounded-full transition-colors ${
          !value ? "bg-accent/15 text-accent-hover" : "text-content-dim hover:text-content-muted"
        }`}
      >
        All
      </button>
      {channels.map((ch) => (
        <button
          key={ch.id}
          onClick={() => onChange(ch.id)}
          className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-full transition-colors ${
            value === ch.id ? "bg-accent/15 text-accent-hover" : "text-content-dim hover:text-content-muted"
          }`}
        >
          <span
            className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ backgroundColor: channelColor(ch.id) }}
          />
          {ch.name || ch.id.slice(0, 8)}
        </button>
      ))}
    </div>
  );
}
