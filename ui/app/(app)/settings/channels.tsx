import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Hash, Lock, Plus } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { Spinner } from "@/src/components/shared/Spinner";
import { useAuthStore } from "@/src/stores/auth";
import { useIsAdmin } from "@/src/hooks/useScope";
import type { Channel } from "@/src/types/api";
import { cn } from "@/src/lib/cn";

function useMyChannels(userId: string | undefined) {
  return useQuery({
    queryKey: ["settings-my-channels", userId ?? null],
    queryFn: async () => {
      const list = await apiFetch<Channel[]>("/api/v1/channels");
      return list.filter((c) => c.user_id && c.user_id === userId);
    },
    enabled: !!userId,
  });
}

export default function MyChannelsPage() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = useIsAdmin();
  const { data, isLoading } = useMyChannels(user?.id);

  return (
    <div className="p-6">
      <div className="flex flex-col gap-4 max-w-2xl">
        <div className="flex flex-row items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <span className="text-text font-semibold text-base">My Channels</span>
            <span className="text-text-muted text-xs">
              Channels you own. Public channels you don't own appear in the
              sidebar but aren't listed here.
            </span>
          </div>
          <Link
            to="/channels/new"
            className="flex flex-row items-center gap-1.5 bg-accent rounded px-3 py-1.5"
          >
            <Plus size={14} color="#fff" />
            <span className="text-white text-xs font-medium">New Channel</span>
          </Link>
        </div>

        {isAdmin && (
          <div className="text-text-dim text-xs">
            Admin tip: this view lists channels you personally own. All
            channels — including unowned ones — are on the home screen and
            sidebar.
          </div>
        )}

        {isLoading ? (
          <div className="p-6">
            <Spinner size={16} />
          </div>
        ) : !data || data.length === 0 ? (
          <div className="flex flex-col items-center gap-2 bg-surface-raised rounded-lg p-8">
            <span className="text-text-muted text-sm">
              You don't own any channels yet.
            </span>
            <Link
              to="/channels/new"
              className="flex flex-row items-center gap-1.5 bg-accent rounded px-3 py-1.5 mt-2"
            >
              <Plus size={12} color="#fff" />
              <span className="text-white text-xs font-medium">
                Create your first channel
              </span>
            </Link>
          </div>
        ) : (
          <div className="flex flex-col gap-1 bg-surface-raised rounded-lg p-2">
            {data.map((ch) => (
              <Link
                key={ch.id}
                to={`/channels/${ch.id}`}
                className={cn(
                  "flex flex-row items-center gap-2 px-3 py-2 rounded-md",
                  "hover:bg-surface-overlay/60 transition-colors",
                )}
              >
                {ch.private ? (
                  <Lock size={14} className="text-text-dim" />
                ) : (
                  <Hash size={14} className="text-text-dim" />
                )}
                <span className="flex-1 text-text text-sm">{ch.name}</span>
                {ch.private && (
                  <span className="text-text-dim text-[10px] uppercase tracking-wider">
                    Private
                  </span>
                )}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
