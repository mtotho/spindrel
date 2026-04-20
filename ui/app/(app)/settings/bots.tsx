import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Bot as BotIcon } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { Spinner } from "@/src/components/shared/Spinner";
import { useIsAdmin } from "@/src/hooks/useScope";
import { cn } from "@/src/lib/cn";

interface MyBotEntry {
  id: string;
  name: string;
  display_name: string | null;
  avatar_url: string | null;
  model: string;
  role: string; // "owner" | "view" | "manage"
}

function useMyBots() {
  return useQuery({
    queryKey: ["settings-my-bots"],
    queryFn: () => apiFetch<MyBotEntry[]>("/auth/me/bots"),
  });
}

function RoleBadge({ role }: { role: string }) {
  const label =
    role === "owner" ? "Owner" : role === "manage" ? "Manage" : "View";
  const className =
    role === "owner"
      ? "bg-accent/20 text-accent"
      : role === "manage"
        ? "bg-amber-500/20 text-amber-400"
        : "bg-surface-overlay text-text-muted";
  return (
    <span
      className={cn(
        "px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider font-medium",
        className,
      )}
    >
      {label}
    </span>
  );
}

export default function MyBotsPage() {
  const isAdmin = useIsAdmin();
  const { data, isLoading } = useMyBots();

  return (
    <div className="p-6">
      <div className="flex flex-col gap-4 max-w-2xl">
        <div className="flex flex-col gap-1">
          <span className="text-text font-semibold text-base">My Bots</span>
          <span className="text-text-muted text-xs">
            Bots you own plus any you've been granted access to.
          </span>
        </div>

        {isAdmin && (
          <div className="text-text-dim text-xs">
            Admin tip: this view only shows bots you personally own or were
            granted. For all bots in the system, see{" "}
            <Link to="/admin/bots" className="text-accent hover:underline">
              Admin → Bots
            </Link>
            .
          </div>
        )}

        {isLoading ? (
          <div className="p-6">
            <Spinner size={16} />
          </div>
        ) : !data || data.length === 0 ? (
          <div className="flex flex-col items-center gap-2 bg-surface-raised rounded-lg p-8">
            <span className="text-text-muted text-sm">
              No bots tied to your account yet.
            </span>
            <span className="text-text-dim text-xs">
              Ask an admin to grant access, or own a bot and it'll show up
              here.
            </span>
          </div>
        ) : (
          <div className="flex flex-col gap-1 bg-surface-raised rounded-lg p-2">
            {data.map((b) => {
              const target = isAdmin ? `/admin/bots/${b.id}` : `/channels/new?bot_id=${b.id}`;
              return (
                <Link
                  key={b.id}
                  to={target}
                  className={cn(
                    "flex flex-row items-center gap-3 px-3 py-2 rounded-md",
                    "hover:bg-surface-overlay/60 transition-colors",
                  )}
                >
                  <div className="flex w-8 h-8 rounded-full bg-accent/20 items-center justify-center overflow-hidden shrink-0">
                    {b.avatar_url ? (
                      <img
                        src={b.avatar_url}
                        style={{ width: 32, height: 32 }}
                        alt={b.name}
                      />
                    ) : (
                      <BotIcon size={16} className="text-accent" />
                    )}
                  </div>
                  <div className="flex-1 flex flex-col">
                    <span className="text-text text-sm">
                      {b.display_name || b.name}
                    </span>
                    <span className="text-text-dim text-[11px]">
                      {b.model}
                    </span>
                  </div>
                  <RoleBadge role={b.role} />
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
