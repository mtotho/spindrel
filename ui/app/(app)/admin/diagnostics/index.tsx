import { useState } from "react";
import { View, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { RefreshCw, AlertTriangle, CheckCircle, Cpu, HardDrive, BookOpen } from "lucide-react";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useIndexingDiagnostics,
  useReindex,
  type FsIndexDiag,
  type ReindexResult,
} from "@/src/api/hooks/useDiagnostics";
import { OperationsPanel } from "./OperationsPanel";
import { DiskUsageSection } from "./DiskUsageSection";
import { StorageSection } from "./StorageSection";

function StatusDot({ ok }: { ok: boolean }) {
  const t = useThemeTokens();
  return (
    <span style={{
      display: "inline-block", width: 8, height: 8, borderRadius: "50%",
      background: ok ? t.success : t.danger, flexShrink: 0,
    }} />
  );
}

function IssuesList({ issues }: { issues: string[] }) {
  const t = useThemeTokens();
  if (issues.length === 0) return null;
  return (
    <div style={{
      padding: "12px 16px", background: t.dangerSubtle,
      border: `1px solid ${t.dangerBorder}`, borderRadius: 8,
      display: "flex", flexDirection: "column", gap: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: t.danger }}>
        <AlertTriangle size={14} /> {issues.length} issue{issues.length !== 1 ? "s" : ""} detected
      </div>
      {issues.map((issue, i) => (
        <div key={i} style={{ fontSize: 12, color: t.danger, paddingLeft: 20 }}>
          {issue}
        </div>
      ))}
    </div>
  );
}

function EmbeddingSection({ data }: { data: { healthy: boolean; model: string; litellm_base_url: string; error: string | null } }) {
  const t = useThemeTokens();
  return (
    <div style={{
      padding: "14px 16px", background: t.inputBg, borderRadius: 8,
      border: `1px solid ${t.surfaceRaised}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <Cpu size={14} color={t.textMuted} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>Embedding Service</span>
        <StatusDot ok={data.healthy} />
        <span style={{ fontSize: 11, color: data.healthy ? t.success : t.danger }}>
          {data.healthy ? "Healthy" : "DOWN"}
        </span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12, color: t.textDim }}>
        <span>Model: <span style={{ color: t.textMuted, fontFamily: "monospace" }}>{data.model}</span></span>
        <span>URL: <span style={{ color: t.textMuted, fontFamily: "monospace" }}>{data.litellm_base_url}</span></span>
      </div>
      {data.error && (
        <div style={{ marginTop: 8, fontSize: 12, color: t.danger, fontFamily: "monospace" }}>
          {data.error}
        </div>
      )}
    </div>
  );
}

function BotIndexCard({ bot }: { bot: FsIndexDiag }) {
  const t = useThemeTokens();
  const hasIssues = (bot.root_exists && bot.files_on_disk > 0 && bot.chunks_in_db === 0)
    || (bot.memory_files_on_disk > 0 && bot.memory_chunks_in_db === 0)
    || !bot.root_exists;
  const borderColor = hasIssues ? t.dangerBorder : t.surfaceRaised;

  return (
    <div style={{
      padding: "14px 16px", background: t.inputBg, borderRadius: 8,
      border: `1px solid ${borderColor}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <HardDrive size={14} color={t.textMuted} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.text, fontFamily: "monospace" }}>
          {bot.bot_id}
        </span>
        <StatusDot ok={!hasIssues} />
      </div>

      {/* Root path */}
      <div style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace", marginBottom: 10, wordBreak: "break-all" }}>
        {bot.workspace_root}
        {!bot.root_exists && <span style={{ color: t.danger, marginLeft: 6 }}>(NOT FOUND)</span>}
      </div>

      {/* Stats grid */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <StatBox label="Files on disk" value={bot.files_on_disk} />
        <StatBox label="Chunks indexed" value={bot.chunks_in_db}
          warn={bot.files_on_disk > 0 && bot.chunks_in_db === 0} />
        <StatBox label="Memory files" value={bot.memory_files_on_disk} />
        <StatBox label="Memory chunks" value={bot.memory_chunks_in_db}
          warn={bot.memory_files_on_disk > 0 && bot.memory_chunks_in_db === 0} />
        <StatBox label="With embeddings" value={bot.chunks_with_embedding}
          warn={bot.chunks_in_db > 0 && bot.chunks_with_embedding === 0} />
        <StatBox label="With TSVector" value={bot.chunks_with_tsv}
          warn={bot.chunks_in_db > 0 && bot.chunks_with_tsv === 0} />
      </div>

      {bot.memory_scheme && (
        <div style={{ marginTop: 8, fontSize: 11, color: t.textDim }}>
          Memory scheme: <span style={{ color: t.textMuted }}>{bot.memory_scheme}</span>
        </div>
      )}
    </div>
  );
}

function StatBox({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  const t = useThemeTokens();
  return (
    <div style={{
      padding: "6px 10px", borderRadius: 6,
      background: warn ? t.dangerSubtle : t.surface,
      border: `1px solid ${warn ? t.dangerBorder : t.surfaceOverlay}`,
    }}>
      <div style={{ fontSize: 10, color: t.textDim, marginBottom: 2 }}>{label}</div>
      <div style={{
        fontSize: 16, fontWeight: 700, fontFamily: "monospace",
        color: warn ? t.danger : t.text,
      }}>
        {value}
      </div>
    </div>
  );
}

function WorkspaceSkillsSection({ data }: { data: Array<{ workspace_id: string; workspace_name: string; skills_enabled: boolean; document_chunks: number; distinct_skills: number }> }) {
  const t = useThemeTokens();
  if (data.length === 0) {
    return (
      <div style={{ padding: 16, fontSize: 12, color: t.textDim, textAlign: "center" }}>
        No shared workspaces configured.
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {data.map((ws) => (
        <div key={ws.workspace_id} style={{
          padding: "12px 16px", background: t.inputBg, borderRadius: 8,
          border: `1px solid ${ws.skills_enabled && ws.document_chunks === 0 ? t.dangerBorder : t.surfaceRaised}`,
          display: "flex", alignItems: "center", gap: 12,
        }}>
          <BookOpen size={14} color={t.textMuted} />
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1 }}>{ws.workspace_name}</span>
          <span style={{
            padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
            background: ws.skills_enabled ? t.successSubtle : "rgba(100,100,100,0.15)",
            color: ws.skills_enabled ? t.success : t.textDim,
          }}>
            {ws.skills_enabled ? "enabled" : "disabled"}
          </span>
          <span style={{ fontSize: 12, color: t.textMuted, fontFamily: "monospace" }}>
            {ws.distinct_skills} skills / {ws.document_chunks} chunks
          </span>
        </div>
      ))}
    </div>
  );
}

function ReindexResultBanner({ result, onDismiss }: { result: ReindexResult; onDismiss: () => void }) {
  const t = useThemeTokens();
  const fsErrors = result.filesystem.filter((f) => f.error);
  const wsErrors = result.workspace_skills.filter((w) => w.error);
  const hasErrors = fsErrors.length > 0 || wsErrors.length > 0;
  const totalIndexed = result.filesystem.reduce((sum, f) => sum + (f.indexed || 0), 0);
  const totalSkills = result.workspace_skills.reduce((sum, w) => sum + (w.embedded || 0), 0);
  const orphansDeleted = result.workspace_skills.reduce((sum, w) => sum + (w.orphans_deleted || 0), 0);

  return (
    <div style={{
      padding: "12px 16px",
      background: hasErrors ? t.dangerSubtle : t.successSubtle,
      border: `1px solid ${hasErrors ? t.dangerBorder : t.success}33`,
      borderRadius: 8, fontSize: 12, lineHeight: 1.6,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ color: hasErrors ? t.danger : t.success }}>
          <strong>Reindex complete:</strong> {totalIndexed} files indexed,
          {" "}{totalSkills} workspace skills embedded
          {orphansDeleted > 0 && `, ${orphansDeleted} orphans cleaned`}
          {result.filesystem.map((f, i) => (
            <div key={i} style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>
              {f.bot_id}: {f.error
                ? <span style={{ color: t.danger }}>{f.error}</span>
                : `${f.indexed} indexed, ${f.skipped} skipped, ${f.removed} removed, ${f.errors} errors`}
            </div>
          ))}
        </div>
        <button onClick={onDismiss} style={{
          background: "none", border: "none", color: t.textDim, cursor: "pointer", fontSize: 16, padding: "0 4px",
        }}>&times;</button>
      </div>
    </div>
  );
}

export default function DiagnosticsScreen() {
  const t = useThemeTokens();
  const { data, isLoading } = useIndexingDiagnostics();
  const reindexMut = useReindex();
  const [reindexResult, setReindexResult] = useState<ReindexResult | null>(null);
  const { refreshing, onRefresh } = usePageRefresh();

  const handleReindex = async () => {
    try {
      const result = await reindexMut.mutateAsync();
      setReindexResult(result);
    } catch { /* mutation error handled by tanstack */ }
  };

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={t.accent} />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Indexing Diagnostics"
        subtitle={data ? (data.healthy ? "All systems healthy" : `${data.issues.length} issue(s)`) : undefined}
        right={
          <button
            onClick={handleReindex}
            disabled={reindexMut.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: t.accent, color: "#fff", cursor: "pointer",
              opacity: reindexMut.isPending ? 0.6 : 1,
            }}
          >
            <RefreshCw size={14} style={reindexMut.isPending ? { animation: "spin 1s linear infinite" } : undefined} />
            {reindexMut.isPending ? "Reindexing..." : "Force Reindex"}
          </button>
        }
      />

      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }} contentContainerStyle={{
        padding: 16, gap: 16, maxWidth: 900,
      }}>
        {/* Active operations (progress bars) */}
        <OperationsPanel />

        {/* Reindex result banner */}
        {reindexResult && (
          <ReindexResultBanner result={reindexResult} onDismiss={() => setReindexResult(null)} />
        )}

        {data && (
          <>
            {/* Issues */}
            <IssuesList issues={data.issues} />

            {/* Overall health */}
            {data.healthy && (
              <div style={{
                padding: "12px 16px", background: t.successSubtle,
                border: `1px solid ${t.success}33`, borderRadius: 8,
                display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: t.success,
              }}>
                <CheckCircle size={14} /> All indexing systems healthy
              </div>
            )}

            {/* CWD */}
            <div style={{ fontSize: 11, color: t.textDim }}>
              Server CWD: <span style={{ fontFamily: "monospace", color: t.textMuted }}>{data.cwd}</span>
              {data.embedding_dimensions && (
                <span style={{ marginLeft: 16 }}>
                  Embedding dims: <span style={{ fontFamily: "monospace", color: t.textMuted }}>{data.embedding_dimensions}</span>
                </span>
              )}
            </div>

            {/* Embedding */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
                Embedding Service
              </div>
              <EmbeddingSection data={data.systems.embedding} />
            </div>

            {/* Disk Usage */}
            <DiskUsageSection />

            {/* Data Retention & Storage */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
                Data Retention & Storage
              </div>
              <StorageSection />
            </div>

            {/* Filesystem Indexing (per bot) */}
            {data.systems.filesystem_indexing.length > 0 && (
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
                  Filesystem Indexing ({data.systems.filesystem_indexing.length} bot{data.systems.filesystem_indexing.length !== 1 ? "s" : ""})
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {data.systems.filesystem_indexing.map((bot) => (
                    <BotIndexCard key={bot.bot_id} bot={bot} />
                  ))}
                </div>
              </div>
            )}

            {/* Workspace Skills */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
                Workspace Skills
              </div>
              <WorkspaceSkillsSection data={data.systems.workspace_skills} />
            </div>

            {/* File-sourced skills */}
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
                File-Sourced Skills
              </div>
              <div style={{
                padding: "14px 16px", background: t.inputBg, borderRadius: 8,
                border: `1px solid ${t.surfaceRaised}`,
                display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12, color: t.textDim,
              }}>
                <span>{data.systems.file_skills.files_on_disk} files on disk</span>
                <span>{data.systems.file_skills.skills_in_db_total} skills in DB ({data.systems.file_skills.skills_in_db_file_sourced} file-sourced)</span>
                <span>{data.systems.file_skills.skill_document_chunks} skill chunks</span>
                <span>{data.systems.file_skills.knowledge_files_on_disk} knowledge files on disk</span>
              </div>
            </div>
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}
