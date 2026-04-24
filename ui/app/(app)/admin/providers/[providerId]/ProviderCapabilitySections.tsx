import { useState, useCallback, useRef } from "react";
import { RefreshCw, Download, Cpu } from "lucide-react";
import {
  useSyncProviderModels,
  useRunningModels,
  type ProviderCapabilities,
  type RunningModel,
  type SyncModelsResult,
} from "@/src/api/hooks/useProviders";
import { Section } from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";

// ---------------------------------------------------------------------------
// Sync Models
// ---------------------------------------------------------------------------

function _fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "never";
  const delta = Math.max(0, Date.now() - new Date(iso).getTime());
  const mins = Math.floor(delta / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function SyncModelsSection({
  providerId,
  lastRefreshTs,
  lastRefreshError,
}: {
  providerId: string;
  lastRefreshTs?: string | null;
  lastRefreshError?: string | null;
}) {
  const t = useThemeTokens();
  const syncMut = useSyncProviderModels(providerId);
  const [result, setResult] = useState<SyncModelsResult | null>(null);

  const handleSync = useCallback(() => {
    setResult(null);
    syncMut.mutate(undefined, {
      onSuccess: (r) => setResult(r),
    });
  }, [syncMut]);

  return (
    <Section title="Sync Models" description="Pull model list from provider API into local database. Auto-refreshed daily by the background catalog job.">
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <button
          onClick={handleSync}
          disabled={syncMut.isPending}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
            padding: "6px 14px", fontSize: 12, fontWeight: 600,
            border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
            background: "transparent", color: t.textMuted, cursor: "pointer",
          }}
        >
          <RefreshCw size={13} style={syncMut.isPending ? { animation: "spin 1s linear infinite" } : undefined} />
          {syncMut.isPending ? "Syncing..." : "Sync Models"}
        </button>
        {result && (
          <span style={{ fontSize: 12, color: t.success }}>
            {result.total} models ({result.created} new, {result.updated} updated)
          </span>
        )}
        {syncMut.isError && (
          <span style={{ fontSize: 12, color: t.danger }}>
            {(syncMut.error as any)?.message || "Sync failed"}
          </span>
        )}
        <span style={{ fontSize: 11, color: t.textDim, marginLeft: "auto" }}>
          Last auto-refresh: {_fmtAgo(lastRefreshTs)}
        </span>
      </div>
      {lastRefreshError && (
        <div className="text-danger text-[11px] mt-1">
          Last refresh error: {lastRefreshError}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Pull Model
// ---------------------------------------------------------------------------

function PullModelSection({ providerId }: { providerId: string }) {
  const t = useThemeTokens();
  const [modelName, setModelName] = useState("");
  const [pulling, setPulling] = useState(false);
  const [progress, setProgress] = useState<{ status: string; completed?: number; total?: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const handlePull = useCallback(async () => {
    if (!modelName.trim()) return;
    setPulling(true);
    setProgress(null);
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const { serverUrl } = useAuthStore.getState();
      const token = getAuthToken();
      if (!serverUrl) { setError("Server not configured"); setPulling(false); return; }
      const base = serverUrl;
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const resp = await fetch(
        `${base}/api/v1/admin/providers/${providerId}/pull-model`,
        {
          method: "POST",
          headers,
          body: JSON.stringify({ model_name: modelName.trim() }),
          signal: controller.signal,
        }
      );

      if (!resp.ok) {
        const body = await resp.text();
        setError(body || `HTTP ${resp.status}`);
        setPulling(false);
        return;
      }

      const reader = resp.body?.getReader();
      if (!reader) {
        setError("No response stream");
        setPulling(false);
        return;
      }

      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() || "";
        for (const line of lines) {
          const trimmed = line.replace(/^data:\s*/, "").trim();
          if (!trimmed) continue;
          try {
            const parsed = JSON.parse(trimmed);
            if (parsed.status === "error") {
              setError(parsed.error || "Pull failed");
            } else if (parsed.status === "success") {
              setProgress({ status: "Complete" });
            } else {
              setProgress(parsed);
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (err: any) {
      if (err.name !== "AbortError") {
        setError(err.message || "Pull failed");
      }
    } finally {
      setPulling(false);
      abortRef.current = null;
    }
  }, [modelName, providerId]);

  const pct =
    progress?.total && progress?.completed
      ? Math.round((progress.completed / progress.total) * 100)
      : null;

  return (
    <Section title="Pull Model" description="Download a model from the registry">
      <div style={{ display: "flex", flexDirection: "row", gap: 8, alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <input
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder="e.g. llama3.1:8b"
            disabled={pulling}
            style={{
              width: "100%", padding: "6px 10px", fontSize: 12,
              background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4, color: t.text, fontFamily: "monospace",
            }}
            onKeyDown={(e) => { if (e.key === "Enter") handlePull(); }}
          />
        </div>
        <button
          onClick={handlePull}
          disabled={pulling || !modelName.trim()}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
            padding: "6px 16px", fontSize: 12, fontWeight: 600,
            border: "none", borderRadius: 6, flexShrink: 0,
            background: !modelName.trim() ? t.surfaceOverlay : t.accent,
            color: !modelName.trim() ? t.textDim : "#fff",
            cursor: !modelName.trim() ? "not-allowed" : "pointer",
          }}
        >
          <Download size={13} />
          {pulling ? "Pulling..." : "Pull"}
        </button>
      </div>
      {progress && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
            {progress.status}{pct != null ? ` (${pct}%)` : ""}
          </div>
          {pct != null && (
            <div style={{
              height: 4, borderRadius: 2, background: t.surfaceRaised, overflow: "hidden",
            }}>
              <div style={{
                width: `${pct}%`, height: "100%", background: t.accent,
                transition: "width 0.3s ease",
              }} />
            </div>
          )}
        </div>
      )}
      {error && (
        <div style={{ marginTop: 6, fontSize: 11, color: t.danger }}>{error}</div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Running Models
// ---------------------------------------------------------------------------

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function RunningModelsSection({ providerId }: { providerId: string }) {
  const t = useThemeTokens();
  const { data: models, isLoading, refetch } = useRunningModels(providerId);

  return (
    <Section title="Running Models" description="Models currently loaded in memory">
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <button
          onClick={() => refetch()}
          disabled={isLoading}
          style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
            padding: "4px 10px", fontSize: 11, fontWeight: 600,
            border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
            background: "transparent", color: t.textMuted, cursor: "pointer",
          }}
        >
          <RefreshCw size={11} />
          Refresh
        </button>
        <span style={{ fontSize: 10, color: t.textDim }}>Auto-refreshes every 10s</span>
      </div>
      {isLoading ? (
        <div style={{ fontSize: 12, color: t.textDim, padding: "4px 0" }}>Loading...</div>
      ) : !models || models.length === 0 ? (
        <div style={{ fontSize: 12, color: t.textDim, padding: "4px 0" }}>No models currently loaded.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {models.map((m: RunningModel, i: number) => (
            <div
              key={m.digest || i}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 10,
                padding: "8px 10px", background: t.surfaceRaised, borderRadius: 6,
                fontSize: 12,
              }}
            >
              <Cpu size={13} color={t.success} style={{ flexShrink: 0 }} />
              <span style={{ color: t.text, fontFamily: "monospace", flex: 1 }}>
                {m.name || m.model}
              </span>
              {m.size_vram > 0 && (
                <span style={{ color: t.accent, fontSize: 11 }}>
                  VRAM: {formatBytes(m.size_vram)}
                </span>
              )}
              {m.size > 0 && (
                <span style={{ color: t.textDim, fontSize: 11 }}>
                  Total: {formatBytes(m.size)}
                </span>
              )}
              {m.expires_at && (
                <span style={{ color: t.textDim, fontSize: 10 }}>
                  expires {new Date(m.expires_at).toLocaleTimeString()}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function ProviderCapabilitySections({
  providerId,
  capabilities,
  lastRefreshTs,
  lastRefreshError,
}: {
  providerId: string;
  capabilities: ProviderCapabilities;
  lastRefreshTs?: string | null;
  lastRefreshError?: string | null;
}) {
  return (
    <>
      {capabilities.list_models && (
        <SyncModelsSection
          providerId={providerId}
          lastRefreshTs={lastRefreshTs}
          lastRefreshError={lastRefreshError}
        />
      )}
      {capabilities.pull_model && (
        <PullModelSection providerId={providerId} />
      )}
      {capabilities.running_models && (
        <RunningModelsSection providerId={providerId} />
      )}
    </>
  );
}
