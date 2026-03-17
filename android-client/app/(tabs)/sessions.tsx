import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { listSessions, type SessionSummary } from "../../src/agent";
import { getSessionId, newSessionId, setSessionId } from "../../src/session";

function formatRelativeTime(iso: string): string {
  try {
    const dt = new Date(iso);
    const now = Date.now();
    const seconds = Math.floor((now - dt.getTime()) / 1000);
    if (seconds < 60) return "just now";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

export default function SessionsScreen() {
  const router = useRouter();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string>();

  const fetchSessions = useCallback(async (showRefresh = false) => {
    if (showRefresh) setRefreshing(true);
    else setLoading(true);
    setError(undefined);

    try {
      const [s, id] = await Promise.all([listSessions(), getSessionId()]);
      setSessions(s);
      setCurrentSessionId(id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load sessions");
      setSessions([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      fetchSessions();
    }, [fetchSessions])
  );

  const handleSwitch = async (session: SessionSummary) => {
    if (session.id === currentSessionId) return;
    await setSessionId(session.id);
    setCurrentSessionId(session.id);
    router.navigate("/");
  };

  const handleNewSession = async () => {
    await newSessionId();
    router.navigate("/");
  };

  return (
    <View style={styles.container}>
      <Pressable style={styles.newButton} onPress={handleNewSession}>
        <Text style={styles.newButtonText}>+ New Session</Text>
      </Pressable>

      {loading && !refreshing && (
        <ActivityIndicator color="#60a5fa" style={{ marginTop: 40 }} size="large" />
      )}

      {error && (
        <View style={styles.errorBox}>
          <Text style={styles.errorText}>{error}</Text>
          <Pressable onPress={() => fetchSessions()} style={styles.retryButton}>
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      )}

      {!loading && !error && sessions.length === 0 && (
        <Text style={styles.emptyText}>No sessions yet. Start chatting to create one.</Text>
      )}

      <ScrollView
        style={styles.list}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => fetchSessions(true)}
            tintColor="#60a5fa"
            colors={["#60a5fa"]}
          />
        }
      >
        {sessions.map((s) => {
          const isActive = s.id === currentSessionId;
          const title = s.title || "(untitled)";
          const time = formatRelativeTime(s.last_active);

          return (
            <Pressable
              key={s.id}
              style={[styles.sessionRow, isActive && styles.sessionRowActive]}
              onPress={() => handleSwitch(s)}
            >
              <View style={styles.sessionHeader}>
                <Text style={[styles.sessionTitle, isActive && styles.sessionTitleActive]} numberOfLines={1}>
                  {title}
                </Text>
                {isActive && <Text style={styles.activeBadge}>active</Text>}
              </View>
              <View style={styles.sessionMeta}>
                <Text style={styles.sessionId}>{s.id.slice(0, 8)}</Text>
                <Text style={styles.sessionDot}>·</Text>
                <Text style={styles.sessionBot}>{s.bot_id}</Text>
                <Text style={styles.sessionDot}>·</Text>
                <Text style={styles.sessionTime}>{time}</Text>
              </View>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#16213e",
  },
  newButton: {
    backgroundColor: "#0f3460",
    marginHorizontal: 16,
    marginTop: 16,
    marginBottom: 8,
    paddingVertical: 14,
    borderRadius: 10,
    alignItems: "center",
  },
  newButtonText: {
    color: "#60a5fa",
    fontWeight: "700",
    fontSize: 16,
  },
  list: {
    flex: 1,
  },
  listContent: {
    padding: 16,
    paddingTop: 8,
    gap: 8,
  },
  sessionRow: {
    backgroundColor: "#1a1a2e",
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#2a2a4e",
  },
  sessionRowActive: {
    borderColor: "#60a5fa",
    backgroundColor: "#0f1b3e",
  },
  sessionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  sessionTitle: {
    color: "#e0e0e0",
    fontSize: 15,
    fontWeight: "600",
    flex: 1,
  },
  sessionTitleActive: {
    color: "#60a5fa",
  },
  activeBadge: {
    color: "#60a5fa",
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginLeft: 8,
    backgroundColor: "#0f3460",
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: "hidden",
  },
  sessionMeta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  sessionId: {
    color: "#6b7280",
    fontSize: 12,
    fontFamily: "monospace",
  },
  sessionDot: {
    color: "#4b5563",
    fontSize: 12,
  },
  sessionBot: {
    color: "#6b7280",
    fontSize: 12,
  },
  sessionTime: {
    color: "#6b7280",
    fontSize: 12,
  },
  emptyText: {
    color: "#6b7280",
    textAlign: "center",
    marginTop: 40,
    fontSize: 15,
    lineHeight: 22,
    paddingHorizontal: 32,
  },
  errorBox: {
    alignItems: "center",
    marginTop: 40,
    paddingHorizontal: 32,
  },
  errorText: {
    color: "#ef4444",
    fontSize: 14,
    textAlign: "center",
    marginBottom: 12,
  },
  retryButton: {
    backgroundColor: "#0f3460",
    paddingVertical: 8,
    paddingHorizontal: 20,
    borderRadius: 6,
  },
  retryText: {
    color: "#60a5fa",
    fontWeight: "600",
  },
});
