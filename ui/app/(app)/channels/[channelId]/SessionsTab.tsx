import { Spinner } from "@/src/components/shared/Spinner";
import { RotateCw } from "lucide-react";
import { EmptyState, Section } from "@/src/components/shared/FormControls";
import { ActionButton, QuietPill, SettingsControlRow, StatusBadge } from "@/src/components/shared/SettingsControls";
import { apiFetch } from "@/src/api/client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Sessions Tab
// ---------------------------------------------------------------------------
export function SessionsTab({ channelId }: { channelId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-sessions", channelId],
    queryFn: async () => {
      const res = await apiFetch<{ sessions: any[] }>(`/api/v1/admin/channels/${channelId}/sessions`);
      return res.sessions;
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/channels/${channelId}/reset`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-sessions", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });

  const switchMutation = useMutation({
    mutationFn: (sessionId: string) =>
      apiFetch(`/api/v1/channels/${channelId}/switch-session`, {
        method: "POST",
        body: JSON.stringify({ session_id: sessionId }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-sessions", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });

  if (isLoading) return <Spinner />;

  return (
    <Section
      title="Conversations"
      description="Channel sessions tied to this channel. Start fresh creates a new active conversation without deleting older sessions."
      action={
        <ActionButton
          label={resetMutation.isPending ? "Resetting..." : "Start Fresh"}
          onPress={() => resetMutation.mutate()}
          disabled={resetMutation.isPending}
          icon={<RotateCw size={12} />}
          size="small"
        />
      }
    >
      <div className="text-[11px] text-text-dim">
        {data?.length ?? 0} conversation{data?.length !== 1 ? "s" : ""}
      </div>
      {!data?.length ? (
        <EmptyState message="No conversations yet." />
      ) : (
        <div className="flex flex-col gap-1.5">
          {data.map((s: any) => (
            <SettingsControlRow key={s.id} active={s.is_active} className="flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className="font-mono text-[12px] text-text">{s.id?.substring(0, 8)}</span>
                  {s.title && <span className="min-w-0 truncate text-[12px] text-text-muted">{s.title}</span>}
                  {s.is_active && <StatusBadge label="ACTIVE" variant="success" />}
                  {s.locked && <StatusBadge label="LOCKED" variant="danger" />}
                  {s.depth > 0 && <QuietPill label={`depth ${s.depth}`} />}
                </div>
                <div className="mt-1 flex flex-wrap gap-2.5 text-[11px] text-text-dim">
                  <span>{s.message_count ?? 0} msgs</span>
                  {s.last_active && <span>{new Date(s.last_active).toLocaleString()}</span>}
                  {s.created_at && <span>created {new Date(s.created_at).toLocaleDateString()}</span>}
                </div>
              </div>
              {!s.is_active && (
                <ActionButton
                  label="Activate"
                  onPress={() => switchMutation.mutate(s.id)}
                  disabled={switchMutation.isPending}
                  variant="secondary"
                  size="small"
                />
              )}
            </SettingsControlRow>
          ))}
        </div>
      )}
    </Section>
  );
}
