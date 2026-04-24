import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, ExternalLink, MessageSquarePlus, Shield, Wrench } from "lucide-react";
import { Link } from "react-router-dom";
import { apiFetch } from "@/src/api/client";
import { useIsAdmin } from "@/src/hooks/useScope";
import { Spinner } from "@/src/components/shared/Spinner";
import { Section } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsSearchBox,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

interface MyBotEntry {
  id: string;
  name: string;
  display_name: string | null;
  avatar_url: string | null;
  model: string;
  role: "owner" | "view" | "manage";
}

function useMyBots() {
  return useQuery({
    queryKey: ["settings-my-bots"],
    queryFn: () => apiFetch<MyBotEntry[]>("/auth/me/bots"),
  });
}

function roleBadge(role: MyBotEntry["role"]) {
  if (role === "owner") return <StatusBadge label="Owner" variant="info" />;
  if (role === "manage") return <StatusBadge label="Manage" variant="warning" />;
  return <QuietPill label="view" />;
}

export default function SettingsBotsPage() {
  const isAdmin = useIsAdmin();
  const [query, setQuery] = useState("");
  const { data, isLoading } = useMyBots();

  const bots = (data ?? []).filter((bot) =>
    `${bot.name} ${bot.display_name ?? ""} ${bot.model} ${bot.role}`.toLowerCase().includes(query.trim().toLowerCase()),
  );

  const owners = bots.filter((bot) => bot.role === "owner");
  const managers = bots.filter((bot) => bot.role === "manage");
  const viewers = bots.filter((bot) => bot.role === "view");

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-5 md:px-6">
      <Section
        title="Bots"
        description="Catalog of bots tied to your account. Channel creation is the primary self-service action today."
      >
        <SettingsStatGrid
          items={[
            { label: "Visible", value: bots.length },
            { label: "Owned", value: owners.length },
            { label: "Manage", value: managers.length, tone: managers.length ? "warning" : "default" },
            { label: "View", value: viewers.length },
          ]}
        />
        <SettingsSearchBox value={query} onChange={setQuery} placeholder="Filter bots..." className="max-w-lg" />
      </Section>

      <Section title="Current access" description="This is the user-scoped catalog. Detailed bot configuration still lives in the canonical admin bot surfaces.">
        {isAdmin && (
          <div className="mb-2 text-[12px] leading-relaxed text-text-dim">
            Admin accounts can jump straight to the canonical bot detail page. This self-service page stays catalog-first instead of pretending to expose a scoped editor that does not exist yet.
          </div>
        )}
        {isLoading ? (
          <div className="py-8"><Spinner size={18} /></div>
        ) : bots.length === 0 ? (
          <EmptyState message={query ? "No bots match that filter." : "No bots are tied to this account yet."} />
        ) : (
          <div className="flex flex-col gap-2">
            {bots.map((bot) => {
              const target = isAdmin ? `/admin/bots/${bot.id}` : `/channels/new?bot_id=${bot.id}`;
              return (
                <Link key={bot.id} to={target}>
                  <SettingsControlRow
                    leading={
                      bot.avatar_url ? (
                        <img src={bot.avatar_url} alt={bot.name} className="h-8 w-8 rounded-full object-cover" />
                      ) : (
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10 text-accent">
                          <Bot size={16} />
                        </div>
                      )
                    }
                    title={bot.display_name || bot.name}
                    description={bot.model}
                    meta={
                      <div className="flex items-center gap-1.5">
                        {roleBadge(bot.role)}
                        {bot.role !== "view" && <QuietPill label="scoped editor next" maxWidthClass="max-w-[140px]" />}
                      </div>
                    }
                    action={
                      isAdmin ? (
                        <ExternalLink size={13} className="text-text-dim" />
                      ) : (
                        <MessageSquarePlus size={13} className="text-text-dim" />
                      )
                    }
                  />
                </Link>
              );
            })}
          </div>
        )}
      </Section>

      <Section title="Next slice" description="Permissions are already differentiated here, but bot editing is still admin-owned. The next phase can add a real scoped editor once the backend contract exists.">
        <div className="grid gap-2 md:grid-cols-3">
          <SettingsControlRow leading={<Shield size={15} />} title="Owner" description="Owns the bot and can administer it through the canonical bot surfaces." />
          <SettingsControlRow leading={<Wrench size={15} />} title="Manage" description="Intended future landing zone for scoped bot editing once the API supports it." />
          <SettingsControlRow leading={<Bot size={15} />} title="View" description="Can inspect the bot here and start channels that use it, but not reconfigure it." />
        </div>
      </Section>
    </div>
  );
}
