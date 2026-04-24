import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Hash, Lock, Plus, Settings2, Users } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { apiFetch } from "@/src/api/client";
import type { Channel } from "@/src/types/api";
import { useAuthStore } from "@/src/stores/auth";
import { useIsAdmin } from "@/src/hooks/useScope";
import { Spinner } from "@/src/components/shared/Spinner";
import { Section } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSearchBox,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

function useVisibleChannels() {
  return useQuery({
    queryKey: ["settings-visible-channels"],
    queryFn: () => apiFetch<Channel[]>("/api/v1/channels"),
  });
}

export default function SettingsChannelsPage() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const isAdmin = useIsAdmin();
  const [query, setQuery] = useState("");
  const { data, isLoading } = useVisibleChannels();

  const owned = (data ?? []).filter((channel) => channel.user_id === user?.id);
  const shared = (data ?? []).filter((channel) => channel.user_id !== user?.id);
  const normalize = (value: string) => value.toLowerCase();
  const filter = (channels: Channel[]) =>
    channels.filter((channel) =>
      normalize(`${channel.name} ${channel.display_name ?? ""} ${channel.bot_id} ${channel.integration ?? ""}`).includes(normalize(query)),
    );

  const visibleOwned = filter(owned);
  const visibleShared = filter(shared);

  if (!user) {
    return <div className="flex h-full items-center justify-center p-6 text-text-muted">Not logged in</div>;
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-5 md:px-6">
      <Section
        title="Channels"
        description="Your owned channels stay editable here. Shared and public channels are listed for quick access and deep links."
        action={<ActionButton label="New channel" onPress={() => navigate("/channels/new")} icon={<Plus size={13} />} />}
      >
        <SettingsStatGrid
          items={[
            { label: "Owned", value: owned.length },
            { label: "Shared", value: shared.length },
            { label: "Visible", value: (data ?? []).length },
            { label: "Private", value: (data ?? []).filter((channel) => channel.private).length },
          ]}
        />
        <SettingsSearchBox value={query} onChange={setQuery} placeholder="Filter channels..." className="max-w-lg" />
      </Section>

      {isAdmin && (
        <Section title="Scope" description="This catalog is user-centric. Fleet-wide lifecycle work still belongs on the home channel list and admin surfaces.">
          <div className="text-[12px] leading-relaxed text-text-dim">
            Admin visibility can exceed ownership. This page shows the channels you can see from the current account, not the canonical fleet management view.
          </div>
        </Section>
      )}

      {isLoading ? (
        <div className="py-8"><Spinner size={18} /></div>
      ) : (
        <>
          <Section title="Owned channels" description="Channels you directly own and can reconfigure from their channel settings page.">
            <SettingsGroupLabel label="Owned" count={visibleOwned.length} icon={<Users size={13} className="text-text-dim" />} />
            {visibleOwned.length === 0 ? (
              <EmptyState message={query ? "No owned channels match that filter." : "You do not own any channels yet."} />
            ) : (
              <div className="flex flex-col gap-2">
                {visibleOwned.map((channel) => (
                  <Link key={channel.id} to={`/channels/${channel.id}/settings`}>
                    <SettingsControlRow
                      leading={channel.private ? <Lock size={15} /> : <Hash size={15} />}
                      title={channel.display_name || channel.name}
                      description={channel.integration ? `${channel.integration} · bot ${channel.bot_id}` : `bot ${channel.bot_id}`}
                      meta={
                        <div className="flex items-center gap-1.5">
                          {channel.private ? <StatusBadge label="Private" variant="warning" /> : <QuietPill label="public" />}
                          {channel.heartbeat_enabled && <QuietPill label="heartbeat" />}
                        </div>
                      }
                      action={<Settings2 size={14} className="text-text-dim" />}
                    />
                  </Link>
                ))}
              </div>
            )}
          </Section>

          <Section title="Shared and public" description="Channels visible to you but owned elsewhere. This page links into the live channel or its settings when available.">
            <SettingsGroupLabel label="Visible" count={visibleShared.length} icon={<Users size={13} className="text-text-dim" />} />
            {visibleShared.length === 0 ? (
              <EmptyState message={query ? "No shared channels match that filter." : "No shared or public channels are visible from this account."} />
            ) : (
              <div className="flex flex-col gap-2">
                {visibleShared.map((channel) => (
                  <Link key={channel.id} to={`/channels/${channel.id}`}>
                    <SettingsControlRow
                      leading={channel.private ? <Lock size={15} /> : <Hash size={15} />}
                      title={channel.display_name || channel.name}
                      description={channel.integration ? `${channel.integration} · bot ${channel.bot_id}` : `bot ${channel.bot_id}`}
                      meta={
                        <div className="flex items-center gap-1.5">
                          {channel.private ? <StatusBadge label="Private" variant="warning" /> : <QuietPill label="public" />}
                          {channel.protected && <QuietPill label="protected" />}
                        </div>
                      }
                    />
                  </Link>
                ))}
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  );
}
