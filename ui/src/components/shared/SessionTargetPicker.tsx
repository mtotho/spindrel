import { MessageSquare, Plus, Star } from "lucide-react";
import { useMemo } from "react";
import { useChannelSessionCatalog } from "@/src/api/hooks/useChannelSessions";
import type { SessionTarget } from "@/src/api/hooks/useTasks";
import { getChannelSessionMeta } from "@/src/lib/channelSessionSurfaces";
import { SelectDropdown, type SelectDropdownOption } from "./SelectDropdown";

interface Props {
  channelId?: string | null;
  value?: SessionTarget | null;
  onChange: (value: SessionTarget) => void;
  disabled?: boolean;
}

function targetToValue(target: SessionTarget | null | undefined): string {
  if (!target || target.mode === "primary") return "primary";
  if (target.mode === "existing") return `existing:${target.session_id}`;
  return "new_each_run";
}

function valueToTarget(value: string): SessionTarget {
  if (value === "new_each_run") return { mode: "new_each_run" };
  if (value.startsWith("existing:")) {
    return { mode: "existing", session_id: value.slice("existing:".length) };
  }
  return { mode: "primary" };
}

export function SessionTargetPicker({
  channelId,
  value,
  onChange,
  disabled = false,
}: Props) {
  const { data: catalog, isLoading } = useChannelSessionCatalog(channelId);
  const selectedValue = targetToValue(value);

  const options = useMemo<SelectDropdownOption[]>(() => {
    const rows = (catalog ?? [])
      .filter((session) => session.surface_kind === "channel")
      .map<SelectDropdownOption>((session) => {
        const label = session.label || session.summary || session.preview || `Session ${session.session_id.slice(0, 8)}`;
        const badges = [
          session.is_active ? "primary" : null,
          session.is_current && !session.is_active ? "current" : null,
          `${session.message_count} messages`,
        ].filter(Boolean).join(" · ");
        return {
          value: `existing:${session.session_id}`,
          label,
          description: getChannelSessionMeta(session),
          meta: badges,
          icon: <MessageSquare size={14} />,
          searchText: `${label} ${session.summary ?? ""} ${session.preview ?? ""}`,
        };
      });
    if (
      value?.mode === "existing"
      && !rows.some((option) => option.value === `existing:${value.session_id}`)
    ) {
      rows.unshift({
        value: `existing:${value.session_id}`,
        label: "Selected session",
        description: value.session_id,
        icon: <MessageSquare size={14} />,
      });
    }

    return [
      {
        value: "primary",
        label: "Primary session",
        description: "Use the channel's current main conversation.",
        icon: <Star size={14} />,
      },
      ...rows,
      {
        value: "new_each_run",
        label: "New session each run",
        description: "Create a fresh visible session for every scheduled run.",
        icon: <Plus size={14} />,
      },
    ];
  }, [catalog, value]);

  return (
    <SelectDropdown
      value={selectedValue}
      options={options}
      onChange={(next) => onChange(valueToTarget(next))}
      placeholder={channelId ? "Choose a session target" : "Select a channel first"}
      disabled={disabled || !channelId}
      loading={isLoading}
      searchable
      searchPlaceholder="Search sessions..."
      popoverWidth="wide"
      renderValue={(option) => (
        <span className="inline-flex min-w-0 items-center gap-1.5">
          <span className="truncate">{option.label}</span>
          {option.meta ? <span className="truncate text-[11px] text-text-dim">{option.meta}</span> : null}
        </span>
      )}
    />
  );
}
