import { ActivityIndicator } from "react-native";
import { RotateCw } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { EmptyState } from "@/src/components/shared/FormControls";
import { apiFetch } from "@/src/api/client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Sessions Tab
// ---------------------------------------------------------------------------
export function SessionsTab({ channelId }: { channelId: string }) {
  const t = useThemeTokens();
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

  if (isLoading) return <ActivityIndicator color={t.accent} />;

  return (
    <>
      {/* Actions bar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button
          onClick={() => resetMutation.mutate()}
          disabled={resetMutation.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 6,
            padding: "6px 14px", fontSize: 12, fontWeight: 600,
            border: "none", cursor: "pointer", borderRadius: 6,
            background: t.accent, color: "#fff",
          }}
        >
          <RotateCw size={12} />
          {resetMutation.isPending ? "Resetting..." : "New Session"}
        </button>
        <span style={{ fontSize: 11, color: t.textDim, alignSelf: "center" }}>
          {data?.length ?? 0} session{data?.length !== 1 ? "s" : ""}
        </span>
      </div>

      {!data?.length ? (
        <EmptyState message="No sessions yet." />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {data.map((s: any) => (
            <div key={s.id} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "10px 12px", background: s.is_active ? "#0d1a0d" : t.surfaceRaised,
              borderRadius: 8, border: `1px solid ${s.is_active ? "#1a3a1a" : t.surfaceOverlay}`,
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 12, color: t.text, fontFamily: "monospace" }}>
                    {s.id?.substring(0, 8)}
                  </span>
                  {s.title && (
                    <span style={{ fontSize: 12, color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, minWidth: 0 }}>
                      {s.title}
                    </span>
                  )}
                  {s.is_active && (
                    <span style={{ fontSize: 9, background: "#166534", color: "#16a34a", padding: "1px 6px", borderRadius: 3, fontWeight: 700 }}>
                      ACTIVE
                    </span>
                  )}
                  {s.locked && (
                    <span style={{ fontSize: 9, background: "rgba(239,68,68,0.12)", color: "#dc2626", padding: "1px 6px", borderRadius: 3, fontWeight: 700 }}>
                      LOCKED
                    </span>
                  )}
                  {s.depth > 0 && (
                    <span style={{ fontSize: 9, background: t.surfaceBorder, color: t.textMuted, padding: "1px 6px", borderRadius: 3 }}>
                      depth {s.depth}
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", gap: 8, fontSize: 11, color: t.textDim, marginTop: 3, flexWrap: "wrap" }}>
                  <span>{s.message_count ?? 0} msgs</span>
                  {s.last_active && <span>{new Date(s.last_active).toLocaleString()}</span>}
                  {s.created_at && <span>created {new Date(s.created_at).toLocaleDateString()}</span>}
                </div>
              </div>
              <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                {!s.is_active && (
                  <button
                    onClick={() => switchMutation.mutate(s.id)}
                    disabled={switchMutation.isPending}
                    style={{
                      padding: "4px 10px", fontSize: 10, fontWeight: 600,
                      border: `1px solid ${t.surfaceBorder}`, borderRadius: 4, cursor: "pointer",
                      background: "transparent", color: "#16a34a",
                    }}
                    title="Switch to this session"
                  >
                    Activate
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
