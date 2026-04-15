import { useState, useCallback, useRef, useEffect } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Check, ChevronDown, ChevronRight, Download, Upload, ShieldAlert } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { writeToClipboard } from "@/src/utils/clipboard";

const SENSITIVE_KEY_PATTERN = /api[_-]?key|secret|token|password|credential|auth[_-]?header/i;

function redactSecrets(obj: any): any {
  if (obj === null || obj === undefined) return obj;
  if (Array.isArray(obj)) return obj.map(redactSecrets);
  if (typeof obj === "object") {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(obj)) {
      if (SENSITIVE_KEY_PATTERN.test(k) && v != null && v !== "" && typeof v !== "object") {
        out[k] = "***REDACTED***";
      } else {
        out[k] = redactSecrets(v);
      }
    }
    return out;
  }
  return obj;
}

function countRedacted(original: any, redacted: any): number {
  if (original === null || original === undefined || typeof original !== "object") return 0;
  if (Array.isArray(original)) {
    return original.reduce((sum, item, i) => sum + countRedacted(item, redacted?.[i]), 0);
  }
  let count = 0;
  for (const k of Object.keys(original)) {
    if (redacted?.[k] === "***REDACTED***" && original[k] !== "***REDACTED***") {
      count++;
    } else {
      count += countRedacted(original[k], redacted?.[k]);
    }
  }
  return count;
}

function Toast({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  const t = useThemeTokens();
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    // Trigger fade-in on next frame
    requestAnimationFrame(() => setVisible(true));
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(onDismiss, 300);
    }, 4000);
    return () => clearTimeout(timer);
  }, [onDismiss]);
  return (
    <div
      style={{
        position: "absolute",
        bottom: 24,
        left: 16,
        right: 16,
        maxWidth: 480,
        alignSelf: "center",
        opacity: visible ? 1 : 0,
        transition: "opacity 0.3s ease",
        backgroundColor: t.warning,
        borderRadius: 8,
        padding: 12,
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        zIndex: 100,
      }}
    >
      <ShieldAlert size={16} color="#000" />
      <span style={{ fontSize: 12, color: "#000", flex: 1 }}>{message}</span>
    </div>
  );
}

function useConfigState() {
  return useQuery({
    queryKey: ["config-state"],
    queryFn: () => apiFetch<Record<string, any>>("/api/v1/admin/config-state"),
  });
}

function CollapsibleSection({
  title,
  badge,
  children,
  defaultOpen = false,
}: {
  title: string;
  badge?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(defaultOpen);
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div style={{ marginBottom: 2 }}>
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex flex-row items-center gap-2 rounded-md px-3 py-2.5 hover:bg-surface-overlay active:bg-surface-overlay"
      >
        <Icon size={14} color={t.textMuted} />
        <span style={{ fontSize: 13, fontWeight: "600", color: t.text }}>
          {title}
        </span>
        {badge ? (
          <span style={{ fontSize: 11, color: t.textDim, marginLeft: 4 }}>
            {badge}
          </span>
        ) : null}
      </button>
      {open ? (
        <div style={{ paddingLeft: 24, paddingBottom: 8 }}>{children}</div>
      ) : null}
    </div>
  );
}

function KV({ k, v }: { k: string; v: any }) {
  const t = useThemeTokens();
  const display =
    v === null || v === undefined
      ? "null"
      : typeof v === "boolean"
        ? v
          ? "true"
          : "false"
        : typeof v === "object"
          ? JSON.stringify(v)
          : String(v);
  return (
    <div className="flex flex-row" style={{ paddingTop: 1, paddingBottom: 1 } as any}>
      <span
        style={{
          fontSize: 12,
          color: t.textMuted,
          fontFamily: "monospace",
          minWidth: 200,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {k}
      </span>
      <span
        style={{
          fontSize: 12,
          color: t.text,
          fontFamily: "monospace",
          flex: 1,
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {display}
      </span>
    </div>
  );
}

function DetailJSON({ data }: { data: any }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  if (!expanded) {
    return (
      <button type="button" onClick={() => setExpanded(true)}>
        <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
          {"{ ... }"}
        </span>
      </button>
    );
  }
  return (
    <button type="button" onClick={() => setExpanded(false)}>
      <span
        style={{ fontSize: 11, color: "#777", fontFamily: "monospace", userSelect: "text" }}
      >
        {JSON.stringify(data, null, 2)}
      </span>
    </button>
  );
}

function SystemSection({ data }: { data: Record<string, any> }) {
  return (
    <>
      {Object.entries(data).map(([k, v]) => (
        <KV key={k} k={k} v={v} />
      ))}
    </>
  );
}

function SettingsSection({ data }: { data: Record<string, Record<string, any>> }) {
  return (
    <>
      {Object.entries(data).map(([group, settings]) => (
        <CollapsibleSection key={group} title={group} badge={`${Object.keys(settings).length}`}>
          {Object.entries(settings).map(([k, v]) => (
            <KV key={k} k={k} v={v} />
          ))}
        </CollapsibleSection>
      ))}
    </>
  );
}

function ProvidersSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((p) => (
        <div key={p.id} style={{ marginBottom: 4 }}>
          <div className="flex flex-row items-center gap-2" style={{ paddingTop: 2, paddingBottom: 2 }}>
            <span style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
              {p.display_name}
            </span>
            <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {p.provider_type}
            </span>
            <span style={{ fontSize: 11, color: p.is_enabled ? t.success : t.danger, fontFamily: "monospace" }}>
              {p.is_enabled ? "enabled" : "disabled"}
            </span>
            <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {p.models.length} models
            </span>
          </div>
          <DetailJSON data={p} />
        </div>
      ))}
    </>
  );
}

function BotsSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((b) => (
        <div key={b.id} style={{ marginBottom: 6 }}>
          <div className="flex flex-row items-center gap-2 flex-wrap" style={{ paddingTop: 2, paddingBottom: 2 }}>
            <span style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
              {b.name}
            </span>
            <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
              {b.model}
            </span>
          </div>
          <div className="flex flex-row flex-wrap gap-x-3" style={{ paddingTop: 1, paddingBottom: 1 }}>
            <Tag label="tools" value={b.local_tools?.length ?? 0} />
            <Tag label="mcp" value={b.mcp_servers?.length ?? 0} />
            <Tag label="skills" value={b.skills?.length ?? 0} />
            <Tag label="memory" value={b.memory_config?.enabled ? "on" : "off"} on={b.memory_config?.enabled} />
            <Tag label="knowledge" value={b.knowledge_config?.enabled ? "on" : "off"} on={b.knowledge_config?.enabled} />
            <Tag label="compaction" value={b.context_compaction ? "on" : "off"} on={b.context_compaction} />
          </div>
          <DetailJSON data={b} />
        </div>
      ))}
    </>
  );
}

function Tag({ label, value, on }: { label: string; value: any; on?: boolean }) {
  const t = useThemeTokens();
  return (
    <span style={{ fontSize: 11, color: on ? t.accent : t.textDim, fontFamily: "monospace" }}>
      {label}:{String(value)}
    </span>
  );
}

function ChannelsSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((ch) => (
        <div key={ch.id} style={{ marginBottom: 4 }}>
          <div className="flex flex-row items-center gap-2" style={{ paddingTop: 2, paddingBottom: 2 }}>
            <span style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
              {ch.name}
            </span>
            <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
              bot:{ch.bot_id}
            </span>
            {ch.integration && (
              <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
                {ch.integration}
              </span>
            )}
          </div>
          <DetailJSON data={ch} />
        </div>
      ))}
    </>
  );
}

function WorkspacesSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((ws) => (
        <div key={ws.id} style={{ marginBottom: 4 }}>
          <div className="flex flex-row items-center gap-2" style={{ paddingTop: 2, paddingBottom: 2 }}>
            <span style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
              {ws.name}
            </span>
            <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
              {ws.image}
            </span>
            <span
              style={{
                fontSize: 11,
                color: ws.status === "running" ? t.success : t.textDim,
                fontFamily: "monospace",
              }}
            >
              {ws.status}
            </span>
            <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {ws.bots?.length ?? 0} bots
            </span>
          </div>
          <DetailJSON data={ws} />
        </div>
      ))}
    </>
  );
}

function SkillsSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((s) => (
        <div key={s.id} className="flex flex-row items-center gap-3" style={{ paddingTop: 2, paddingBottom: 2 }}>
          <span style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600", minWidth: 160 }}>
            {s.name}
          </span>
          <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {s.source_type}
          </span>
          <span style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
            {s.chunk_count} chunks
          </span>
        </div>
      ))}
    </>
  );
}

function TasksSection({ data }: { data: any[] }) {
  const tk = useThemeTokens();
  if (data.length === 0) {
    return <span style={{ fontSize: 12, color: tk.textDim, fontFamily: "monospace" }}>No recurring tasks</span>;
  }
  return (
    <>
      {data.map((t) => (
        <div key={t.id} className="flex flex-row items-center gap-3" style={{ paddingTop: 2, paddingBottom: 2 }}>
          <span style={{ fontSize: 12, color: tk.text, fontFamily: "monospace", fontWeight: "600" }}>
            {t.title || t.bot_id}
          </span>
          <span style={{ fontSize: 11, color: tk.textMuted, fontFamily: "monospace" }}>
            {t.task_type}
          </span>
          {t.recurrence && (
            <span style={{ fontSize: 11, color: tk.accent, fontFamily: "monospace" }}>
              every {t.recurrence}
            </span>
          )}
          <span
            style={{
              fontSize: 11,
              color: t.status === "running" ? tk.success : t.status === "pending" ? tk.warning : tk.textDim,
              fontFamily: "monospace",
            }}
          >
            {t.status}
          </span>
        </div>
      ))}
    </>
  );
}

function UsersSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  return (
    <>
      {data.map((u) => (
        <div key={u.id} className="flex flex-row items-center gap-3" style={{ paddingTop: 2, paddingBottom: 2 }}>
          <span style={{ fontSize: 12, color: t.text, fontFamily: "monospace", fontWeight: "600" }}>
            {u.display_name}
          </span>
          <span style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace" }}>
            {u.email}
          </span>
          <span style={{ fontSize: 11, color: u.is_admin ? t.accent : t.textDim, fontFamily: "monospace" }}>
            {u.is_admin ? "admin" : "user"}
          </span>
          {!u.is_active && (
            <span style={{ fontSize: 11, color: t.danger, fontFamily: "monospace" }}>
              inactive
            </span>
          )}
        </div>
      ))}
    </>
  );
}

function GenericListSection({ data }: { data: any[] }) {
  const t = useThemeTokens();
  if (data.length === 0) {
    return <span style={{ fontSize: 12, color: t.textDim, fontFamily: "monospace" }}>None</span>;
  }
  return (
    <>
      {data.map((item, i) => (
        <div key={item.id ?? item.bot_id ?? i} style={{ marginBottom: 4 }}>
          <DetailJSON data={item} />
        </div>
      ))}
    </>
  );
}

function downloadJson(data: any, filename: string) {
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function ConfigStatePage() {
  const t = useThemeTokens();
  const { data, isLoading, error } = useConfigState();
  const queryClient = useQueryClient();
  const { refreshing, onRefresh } = usePageRefresh();
  const [copied, setCopied] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [restoreResult, setRestoreResult] = useState<{ status: string; summary: Record<string, any> } | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [confirmPayload, setConfirmPayload] = useState<Record<string, any> | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleCopy = useCallback(async () => {
    if (!data) return;
    try {
      const redacted = redactSecrets(data);
      const n = countRedacted(data, redacted);
      await writeToClipboard(JSON.stringify(redacted, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      if (n > 0) {
        setToastMessage(
          `${n} secret${n > 1 ? "s" : ""} redacted from clipboard. Use Backup to export with secrets.`
        );
      }
    } catch {
      // fallback: noop
    }
  }, [data]);

  const handleBackup = useCallback(() => {
    if (!data) return;
    const date = new Date().toISOString().slice(0, 10);
    downloadJson(data, `config-backup-${date}.json`);
  }, [data]);

  const handleFileSelect = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const payload = JSON.parse(text);
      setConfirmPayload(payload);
      setRestoreError(null);
      setRestoreResult(null);
    } catch {
      setRestoreError("Invalid JSON file");
    }
    // Reset file input so same file can be selected again
    e.target.value = "";
  }, []);

  const handleRestore = useCallback(async () => {
    if (!confirmPayload) return;
    setRestoring(true);
    setRestoreError(null);
    setRestoreResult(null);
    try {
      const result = await apiFetch<{ status: string; summary: Record<string, any> }>(
        "/api/v1/admin/config-state/restore",
        { method: "POST", body: JSON.stringify(confirmPayload) }
      );
      setRestoreResult(result);
      setConfirmPayload(null);
      // Refresh the config state data
      queryClient.invalidateQueries({ queryKey: ["config-state"] });
    } catch (err: any) {
      setRestoreError(err?.message || "Restore failed");
    } finally {
      setRestoring(false);
    }
  }, [confirmPayload, queryClient]);

  const handleCancelRestore = useCallback(() => {
    setConfirmPayload(null);
    setRestoreError(null);
  }, []);

  const HeaderButtons = (
    <div className="flex flex-row items-center gap-1">
      <button
        type="button"
        onClick={handleBackup}
        disabled={!data}
        className="flex flex-row items-center gap-1.5 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay"
        style={{ opacity: data ? 1 : 0.4 }}
      >
        <Download size={14} color={t.accent} />
        <span style={{ fontSize: 12, color: t.accent }}>Backup</span>
      </button>
      <button
        type="button"
        onClick={handleFileSelect}
        className="flex flex-row items-center gap-1.5 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay"
      >
        <Upload size={14} color={t.warning} />
        <span style={{ fontSize: 12, color: t.warning }}>Restore</span>
      </button>
      <button
        type="button"
        onClick={handleCopy}
        disabled={!data}
        className="flex flex-row items-center gap-1.5 rounded-md px-3 py-1.5 hover:bg-surface-overlay active:bg-surface-overlay"
        style={{ opacity: data ? 1 : 0.4 }}
      >
        {copied ? <Check size={14} color={t.success} /> : <Copy size={14} color={t.textMuted} />}
        <span style={{ fontSize: 12, color: copied ? t.success : t.textMuted }}>
          {copied ? "Copied" : "Copy"}
        </span>
      </button>
    </div>
  );

  // Count sections in confirm payload
  const confirmSections = confirmPayload
    ? Object.entries(confirmPayload)
        .filter(([, v]) => Array.isArray(v) && v.length > 0)
        .map(([k, v]) => `${k}: ${(v as any[]).length}`)
    : [];

  return (
    <div style={{ flex: 1, backgroundColor: t.surface }}>
      {/* Hidden file input for restore */}
      <input
        ref={fileInputRef as any}
        type="file"
        accept=".json"
        style={{ display: "none" }}
        onChange={handleFileChange as any}
      />

      <PageHeader variant="list" title="Config State" right={HeaderButtons} />
      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, maxWidth: 960 }}
      >
        {/* Restore confirmation dialog */}
        {confirmPayload && (
          <div
            style={{
              backgroundColor: t.surfaceRaised,
              borderRadius: 8,
              padding: 16,
              marginBottom: 16,
              borderWidth: 1,
              borderColor: t.warning,
            }}
          >
            <span style={{ fontSize: 14, fontWeight: "600", color: t.warning, marginBottom: 8 }}>
              Confirm Restore
            </span>
            <span style={{ fontSize: 12, color: t.text, marginBottom: 8 }}>
              This will upsert the following sections:
            </span>
            {confirmSections.map((s) => (
              <span key={s} style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace", paddingLeft: 8 }}>
                {s}
              </span>
            ))}
            <div className="flex flex-row gap-3" style={{ marginTop: 12 }}>
              <button
                type="button"
                onClick={handleRestore}
                disabled={restoring}
                style={{
                  backgroundColor: t.warning,
                  paddingHorizontal: 16,
                  paddingTop: 6, paddingBottom: 6,
                  borderRadius: 6,
                  opacity: restoring ? 0.5 : 1,
                } as any}
              >
                <span style={{ fontSize: 12, fontWeight: "600", color: "#000" }}>
                  {restoring ? "Restoring..." : "Confirm Restore"}
                </span>
              </button>
              <button
                type="button"
                onClick={handleCancelRestore}
                disabled={restoring}
                style={{
                  paddingHorizontal: 16,
                  paddingTop: 6, paddingBottom: 6,
                  borderRadius: 6,
                  borderWidth: 1,
                  borderColor: t.textDim,
                } as any}
              >
                <span style={{ fontSize: 12, color: t.textMuted }}>Cancel</span>
              </button>
            </div>
          </div>
        )}

        {/* Restore result */}
        {restoreResult && (
          <div
            style={{
              backgroundColor: t.successSubtle,
              borderRadius: 8,
              padding: 16,
              marginBottom: 16,
              borderWidth: 1,
              borderColor: t.success,
            }}
          >
            <span style={{ fontSize: 13, fontWeight: "600", color: t.success, marginBottom: 8 }}>
              Restore Complete
            </span>
            {Object.entries(restoreResult.summary).map(([section, counts]) => (
              <span key={section} style={{ fontSize: 11, color: t.textMuted, fontFamily: "monospace", paddingLeft: 8 }}>
                {section}: {(counts as any).updated ?? 0} upserted
              </span>
            ))}
            <button type="button" onClick={() => setRestoreResult(null)} style={{ marginTop: 8 }}>
              <span style={{ fontSize: 11, color: t.textDim }}>Dismiss</span>
            </button>
          </div>
        )}

        {/* Restore error */}
        {restoreError && (
          <div
            style={{
              backgroundColor: t.dangerSubtle,
              borderRadius: 8,
              padding: 12,
              marginBottom: 16,
              borderWidth: 1,
              borderColor: t.danger,
            }}
          >
            <span style={{ fontSize: 12, color: t.danger }}>{restoreError}</span>
            <button type="button" onClick={() => setRestoreError(null)} style={{ marginTop: 4 }}>
              <span style={{ fontSize: 11, color: t.textDim }}>Dismiss</span>
            </button>
          </div>
        )}

        {isLoading ? (
          <div style={{ display: "flex", padding: 40, alignItems: "center" }}>
            <Spinner color={t.accent} />
          </div>
        ) : error ? (
          <span style={{ color: t.danger, fontSize: 13 }}>
            Failed to load config state
          </span>
        ) : data ? (
          <div style={{ display: "flex", gap: 2 }}>
            <CollapsibleSection title="System" defaultOpen>
              <SystemSection data={data.system} />
            </CollapsibleSection>

            <CollapsibleSection
              title="Global Fallback Models"
              badge={`${data.global_fallback_models?.length ?? 0}`}
            >
              {(data.global_fallback_models || []).length === 0 ? (
                <span style={{ fontSize: 12, color: t.textDim, fontFamily: "monospace" }}>
                  None configured
                </span>
              ) : (
                data.global_fallback_models.map((m: any, i: number) => (
                  <KV key={i} k={`[${i}]`} v={m.model || JSON.stringify(m)} />
                ))
              )}
            </CollapsibleSection>

            <CollapsibleSection
              title="Settings"
              badge={`${Object.keys(data.settings || {}).length} groups`}
            >
              <SettingsSection data={data.settings} />
            </CollapsibleSection>

            <CollapsibleSection title="Providers" badge={`${data.providers?.length ?? 0}`}>
              <ProvidersSection data={data.providers || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Bots" badge={`${data.bots?.length ?? 0}`}>
              <BotsSection data={data.bots || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Channels" badge={`${data.channels?.length ?? 0}`}>
              <ChannelsSection data={data.channels || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Workspaces" badge={`${data.workspaces?.length ?? 0}`}>
              <WorkspacesSection data={data.workspaces || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Skills" badge={`${data.skills?.length ?? 0}`}>
              <SkillsSection data={data.skills || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Tasks" badge={`${data.tasks?.length ?? 0}`}>
              <TasksSection data={data.tasks || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Users" badge={`${data.users?.length ?? 0}`}>
              <UsersSection data={data.users || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Sandbox Profiles" badge={`${data.sandbox_profiles?.length ?? 0}`}>
              <GenericListSection data={data.sandbox_profiles || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Sandbox Bot Access" badge={`${data.sandbox_bot_access?.length ?? 0}`}>
              <GenericListSection data={data.sandbox_bot_access || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Tool Policy Rules" badge={`${data.tool_policy_rules?.length ?? 0}`}>
              <GenericListSection data={data.tool_policy_rules || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Prompt Templates" badge={`${data.prompt_templates?.length ?? 0}`}>
              <GenericListSection data={data.prompt_templates || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Bot Personas" badge={`${data.bot_personas?.length ?? 0}`}>
              <GenericListSection data={data.bot_personas || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Channel Integrations" badge={`${data.channel_integrations?.length ?? 0}`}>
              <GenericListSection data={data.channel_integrations || []} />
            </CollapsibleSection>

            <CollapsibleSection title="Channel Heartbeats" badge={`${data.channel_heartbeats?.length ?? 0}`}>
              <GenericListSection data={data.channel_heartbeats || []} />
            </CollapsibleSection>
          </div>
        ) : null}
      </RefreshableScrollView>
      {toastMessage && <Toast message={toastMessage} onDismiss={() => setToastMessage(null)} />}
    </div>
  );
}
