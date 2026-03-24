import { useState, useCallback } from "react";
import { View, Text, Pressable, ScrollView, ActivityIndicator } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { Clock, AlertCircle, CheckCircle2, Loader2, Filter } from "lucide-react";
import { apiFetch } from "@/src/api/client";

interface TaskItem {
  id: string;
  status: string;
  bot_id: string;
  prompt: string;
  result?: string;
  error?: string;
  dispatch_type: string;
  recurrence?: string;
  channel_id?: string;
  created_at?: string;
  scheduled_at?: string;
  run_at?: string;
  completed_at?: string;
}

interface TasksResponse {
  tasks: TaskItem[];
  total: number;
  limit: number;
  offset: number;
}

const STATUS_FILTERS = [
  { label: "All", value: "" },
  { label: "Pending", value: "pending" },
  { label: "Running", value: "running" },
  { label: "Complete", value: "complete" },
  { label: "Failed", value: "failed" },
];

const STATUS_STYLES: Record<string, { bg: string; fg: string; icon: any }> = {
  pending: { bg: "#333", fg: "#999", icon: Clock },
  running: { bg: "#1e3a5f", fg: "#93c5fd", icon: Loader2 },
  complete: { bg: "#166534", fg: "#86efac", icon: CheckCircle2 },
  failed: { bg: "#7f1d1d", fg: "#fca5a5", icon: AlertCircle },
};

export default function TasksScreen() {
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 25;

  const { data, isLoading } = useQuery({
    queryKey: ["admin-tasks", statusFilter, page],
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(pageSize), offset: String(page * pageSize) });
      if (statusFilter) params.set("status", statusFilter);
      return apiFetch<TasksResponse>(`/api/v1/admin/tasks?${params}`);
    },
  });

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  return (
    <View className="flex-1 bg-surface">
      {/* Header */}
      <View className="px-6 pt-5 pb-3">
        <Text className="text-text text-lg font-bold">Tasks</Text>
        <Text className="text-text-dim text-xs mt-0.5">
          {data ? `${data.total} total` : "Loading..."}
        </Text>
      </View>

      {/* Filters */}
      <View className="px-6 pb-3">
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => { setStatusFilter(f.value); setPage(0); }}
              style={{
                padding: "4px 12px", borderRadius: 6, fontSize: 12, fontWeight: 500,
                border: "none", cursor: "pointer",
                background: statusFilter === f.value ? "#3b82f6" : "#222",
                color: statusFilter === f.value ? "#fff" : "#999",
                transition: "all 0.15s",
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
      </View>

      {/* Task list */}
      {isLoading ? (
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color="#3b82f6" />
        </View>
      ) : (
        <ScrollView className="flex-1" contentContainerStyle={{ paddingHorizontal: 24, paddingBottom: 24 }}>
          {!data?.tasks.length ? (
            <View className="items-center py-12">
              <Text className="text-text-dim text-sm">No tasks found.</Text>
            </View>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {data.tasks.map((task) => {
                const s = STATUS_STYLES[task.status] || STATUS_STYLES.pending;
                const StatusIcon = s.icon;
                return (
                  <div key={task.id} style={{
                    padding: "12px 16px", background: "#1a1a1a", borderRadius: 10,
                    border: "1px solid #2a2a2a",
                  }}>
                    {/* Top row: status + id + bot */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <StatusIcon size={14} color={s.fg} />
                        <span style={{ fontFamily: "monospace", fontSize: 12, color: "#e5e5e5" }}>
                          {task.id.substring(0, 12)}...
                        </span>
                        <span style={{
                          fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                          background: s.bg, color: s.fg,
                        }}>
                          {task.status}
                        </span>
                      </div>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11 }}>
                        {task.recurrence && (
                          <span style={{ background: "#92400e", color: "#fcd34d", padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 600 }}>
                            {task.recurrence}
                          </span>
                        )}
                        <span style={{ color: "#666" }}>{task.bot_id}</span>
                        <span style={{ color: "#555" }}>{task.dispatch_type}</span>
                      </div>
                    </div>

                    {/* Prompt */}
                    {task.prompt && (
                      <div style={{
                        fontSize: 12, color: "#999", whiteSpace: "pre-wrap",
                        maxHeight: 60, overflow: "hidden", marginBottom: 4,
                      }}>
                        {task.prompt.substring(0, 200)}{task.prompt.length > 200 ? "..." : ""}
                      </div>
                    )}

                    {/* Error */}
                    {task.error && (
                      <div style={{ fontSize: 11, color: "#fca5a5", marginBottom: 4 }}>
                        {task.error.substring(0, 200)}
                      </div>
                    )}

                    {/* Timestamps */}
                    <div style={{ display: "flex", gap: 16, fontSize: 10, color: "#555", marginTop: 4 }}>
                      {task.created_at && <span>Created: {new Date(task.created_at).toLocaleString()}</span>}
                      {task.scheduled_at && <span>Scheduled: {new Date(task.scheduled_at).toLocaleString()}</span>}
                      {task.completed_at && <span>Completed: {new Date(task.completed_at).toLocaleString()}</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={{ display: "flex", justifyContent: "center", gap: 8, marginTop: 16 }}>
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                style={{
                  padding: "4px 12px", borderRadius: 6, fontSize: 12, border: "none", cursor: "pointer",
                  background: page === 0 ? "#1a1a1a" : "#333", color: page === 0 ? "#555" : "#e5e5e5",
                }}
              >
                Previous
              </button>
              <span style={{ fontSize: 12, color: "#666", alignSelf: "center" }}>
                {page + 1} / {totalPages}
              </span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                style={{
                  padding: "4px 12px", borderRadius: 6, fontSize: 12, border: "none", cursor: "pointer",
                  background: page >= totalPages - 1 ? "#1a1a1a" : "#333",
                  color: page >= totalPages - 1 ? "#555" : "#e5e5e5",
                }}
              >
                Next
              </button>
            </div>
          )}
        </ScrollView>
      )}
    </View>
  );
}
