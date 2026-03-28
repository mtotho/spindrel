import React, { useState } from "react";
import { Package } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import {
  TextInput, SelectInput, Toggle, FormRow, Row, Col,
} from "@/src/components/shared/FormControls";
import type { BotConfig, BotEditorData } from "@/src/types/api";

export function WorkspaceSection({
  editorData, draft, update,
}: { editorData: BotEditorData; draft: BotConfig; update: (p: Partial<BotConfig>) => void }) {
  const t = useThemeTokens();
  const ws = draft.workspace || { enabled: false };
  const docker = ws.docker || {};
  const host = ws.host || {};
  const indexing = ws.indexing || {};

  const setWs = (patch: Record<string, any>) => update({ workspace: { ...ws, ...patch } });
  const setDocker = (patch: Record<string, any>) => setWs({ docker: { ...docker, ...patch } });
  const setHost = (patch: Record<string, any>) => setWs({ host: { ...host, ...patch } });
  const setIndexing = (patch: Record<string, any>) => setWs({ indexing: { ...indexing, ...patch } });

  // Env var add state
  const [newEnvKey, setNewEnvKey] = useState("");
  const [newEnvVal, setNewEnvVal] = useState("");
  const [newHostPort, setNewHostPort] = useState("");
  const [newContainerPort, setNewContainerPort] = useState("");
  const [newMountHost, setNewMountHost] = useState("");
  const [newMountContainer, setNewMountContainer] = useState("");
  const [newMountMode, setNewMountMode] = useState("rw");
  const [newCmd, setNewCmd] = useState("");
  const [newCmdSubs, setNewCmdSubs] = useState("");
  const [newBlocked, setNewBlocked] = useState("");
  const [newEnvPass, setNewEnvPass] = useState("");
  const [newPattern, setNewPattern] = useState("");
  const [newSegPrefix, setNewSegPrefix] = useState("");
  const [newSegModel, setNewSegModel] = useState("");

  const envEntries = Object.entries(docker.env || {});
  const ports: any[] = docker.ports || [];
  const mounts: any[] = docker.mounts || [];
  const commands: any[] = host.commands || [];
  const blocked: string[] = host.blocked_patterns || [];
  const envPass: string[] = host.env_passthrough || [];
  const patterns: string[] = indexing.patterns || [];
  const segments: any[] = indexing.segments || [];

  const rowStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 6, padding: "3px 6px",
    background: t.inputBg, borderRadius: 4, fontSize: 11,
  };
  const removeBtn = (onClick: () => void) => (
    <button onClick={onClick} style={{ background: "none", border: "none", cursor: "pointer", padding: 0, color: "#f87171", fontSize: 12 }}>×</button>
  );
  const addBtn = (label: string, onClick: () => void) => (
    <button onClick={onClick} style={{
      padding: "3px 10px", fontSize: 11, background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
      borderRadius: 4, color: t.textMuted, cursor: "pointer",
    }}>{label}</button>
  );
  const miniInput = (value: string, onChange: (v: string) => void, placeholder: string, style?: React.CSSProperties) => (
    <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder}
      style={{ background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4, padding: "3px 6px", fontSize: 11, color: t.text, outline: "none", ...style }}
      onKeyDown={(e) => { if (e.key === "Enter") e.preventDefault(); }}
    />
  );

  const inSharedWorkspace = !!draft.shared_workspace_id;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Shared workspace banner */}
      {inSharedWorkspace && (
        <div style={{
          display: "flex", flexDirection: "column", gap: 8,
          padding: "14px 16px", background: "rgba(139,92,246,0.06)",
          border: "1px solid rgba(139,92,246,0.15)", borderRadius: 10,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Package size={14} color="#c4b5fd" />
            <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>Shared Workspace</span>
            <span style={{
              padding: "2px 8px", borderRadius: 4, fontSize: 10, fontWeight: 600,
              background: draft.shared_workspace_role === "orchestrator" ? "rgba(168,85,247,0.15)" : "rgba(59,130,246,0.1)",
              color: draft.shared_workspace_role === "orchestrator" ? "#c4b5fd" : "#93c5fd",
            }}>
              {draft.shared_workspace_role || "member"}
            </span>
          </div>
          <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5 }}>
            This bot is connected to a shared workspace. Container settings (image, ports, mounts, env) are managed at the workspace level.
            {draft.shared_workspace_role === "orchestrator"
              ? " As orchestrator, this bot has full access to /workspace."
              : " As a member, this bot is scoped to /workspace/bots/" + (draft.id || "...") + "/."
            }
          </div>
          <a
            href={`/admin/workspaces/${draft.shared_workspace_id}`}
            style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 12, fontWeight: 600, color: "#93c5fd",
              textDecoration: "none", alignSelf: "flex-start",
            }}
          >
            Open Workspace Settings &rarr;
          </a>
        </div>
      )}

      {/* Per-bot workspace toggle — only when NOT in a shared workspace */}
      {!inSharedWorkspace && (
        <Toggle value={ws.enabled ?? false} onChange={(v) => setWs({ enabled: v })} label="Enable Workspace"
          description="Auto-injects exec_command, search_workspace, delegate_to_exec tools." />
      )}

      {(ws.enabled || inSharedWorkspace) && (
        <>
          {/* Per-bot docker/host settings — only when NOT in a shared workspace */}
          {!inSharedWorkspace && (
            <>
              <Row gap={12}>
                <Col>
                  <FormRow label="Type">
                    <SelectInput value={ws.type || "docker"} onChange={(v) => setWs({ type: v })}
                      options={[{ label: "Docker Container", value: "docker" }, { label: "Host Execution", value: "host" }]} />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Timeout (seconds)">
                    <TextInput value={String(ws.timeout ?? "")} onChangeText={(v) => setWs({ timeout: v ? parseInt(v) : null })} placeholder="30" type="number" />
                  </FormRow>
                </Col>
                <Col>
                  <FormRow label="Max Output Bytes">
                    <TextInput value={String(ws.max_output_bytes ?? "")} onChangeText={(v) => setWs({ max_output_bytes: v ? parseInt(v) : null })} placeholder="65536" type="number" />
                  </FormRow>
                </Col>
              </Row>

              {/* Docker panel */}
              {(ws.type || "docker") === "docker" && (
                <div style={{ borderLeft: "2px solid #1e3a5f", paddingLeft: 12, display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Docker Settings</div>
                  <Row gap={12}>
                    <Col><FormRow label="Image"><TextInput value={docker.image || ""} onChangeText={(v) => setDocker({ image: v })} placeholder="python:3.12-slim" /></FormRow></Col>
                    <Col><FormRow label="Network"><SelectInput value={docker.network || "none"} onChange={(v) => setDocker({ network: v })}
                      options={[{ label: "none", value: "none" }, { label: "bridge", value: "bridge" }, { label: "host", value: "host" }]} /></FormRow></Col>
                  </Row>
                  <Row gap={12}>
                    <Col><FormRow label="Run as User"><TextInput value={docker.user || ""} onChangeText={(v) => setDocker({ user: v })} placeholder="image default" /></FormRow></Col>
                    <Col><FormRow label="CPUs"><TextInput value={String(docker.cpus ?? "")} onChangeText={(v) => setDocker({ cpus: v ? parseFloat(v) : null })} placeholder="unlimited" type="number" /></FormRow></Col>
                    <Col><FormRow label="Memory"><TextInput value={docker.memory || ""} onChangeText={(v) => setDocker({ memory: v })} placeholder="e.g. 512m, 2g" /></FormRow></Col>
                  </Row>
                  <Toggle value={docker.read_only_root ?? false} onChange={(v) => setDocker({ read_only_root: v })} label="Read-only root filesystem" />

                  {/* Env vars */}
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Environment Variables</div>
                    {envEntries.map(([k, v]) => (
                      <div key={k} style={rowStyle}>
                        <span style={{ fontFamily: "monospace", color: "#93c5fd", minWidth: 60, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis" }}>{k}</span>
                        <span style={{ color: t.textDim }}>=</span>
                        <span style={{ fontFamily: "monospace", color: t.textMuted, flex: 1 }}>{v as string}</span>
                        {removeBtn(() => { const e = { ...docker.env }; delete e[k]; setDocker({ env: e }); })}
                      </div>
                    ))}
                    <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                      {miniInput(newEnvKey, setNewEnvKey, "KEY", { flex: 1, maxWidth: 120 })}
                      <span style={{ color: t.textDim, fontSize: 11 }}>=</span>
                      {miniInput(newEnvVal, setNewEnvVal, "value", { flex: 1 })}
                      {addBtn("Add", () => {
                        if (newEnvKey.trim()) { setDocker({ env: { ...docker.env, [newEnvKey.trim()]: newEnvVal } }); setNewEnvKey(""); setNewEnvVal(""); }
                      })}
                    </div>
                  </div>

                  {/* Ports */}
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Port Mappings</div>
                    {ports.map((p: any, i: number) => (
                      <div key={i} style={rowStyle}>
                        <span style={{ fontFamily: "monospace", color: "#93c5fd" }}>{p.host_port ? `${p.host_port}:${p.container_port}` : p.container_port}</span>
                        {removeBtn(() => setDocker({ ports: ports.filter((_, j: number) => j !== i) }))}
                      </div>
                    ))}
                    <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                      {miniInput(newHostPort, setNewHostPort, "host (opt)", { flex: 1, maxWidth: 100 })}
                      <span style={{ color: t.textDim, fontSize: 11 }}>:</span>
                      {miniInput(newContainerPort, setNewContainerPort, "container", { flex: 1, maxWidth: 100 })}
                      {addBtn("Add", () => {
                        if (newContainerPort.trim()) { setDocker({ ports: [...ports, { host_port: newHostPort.trim(), container_port: newContainerPort.trim() }] }); setNewHostPort(""); setNewContainerPort(""); }
                      })}
                    </div>
                  </div>

                  {/* Mounts */}
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Extra Volume Mounts</div>
                    <div style={{ fontSize: 10, color: t.textDim, marginBottom: 4 }}>Workspace root always mounted at /workspace.</div>
                    {mounts.map((m: any, i: number) => (
                      <div key={i} style={rowStyle}>
                        <span style={{ fontFamily: "monospace", color: "#93c5fd", flex: 1 }}>{m.host_path} : {m.container_path} : {m.mode || "rw"}</span>
                        {removeBtn(() => setDocker({ mounts: mounts.filter((_, j: number) => j !== i) }))}
                      </div>
                    ))}
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                      {miniInput(newMountHost, setNewMountHost, "host path", { flex: 1, minWidth: 80 })}
                      <span style={{ color: t.textDim, fontSize: 11 }}>:</span>
                      {miniInput(newMountContainer, setNewMountContainer, "container path", { flex: 1, minWidth: 80 })}
                      <select value={newMountMode} onChange={(e) => setNewMountMode(e.target.value)}
                        style={{ background: t.surface, border: `1px solid ${t.surfaceBorder}`, borderRadius: 4, padding: "3px 4px", fontSize: 11, color: t.text, width: 50 }}>
                        <option value="rw">rw</option>
                        <option value="ro">ro</option>
                      </select>
                      {addBtn("Add", () => {
                        if (newMountHost.trim() && newMountContainer.trim()) {
                          setDocker({ mounts: [...mounts, { host_path: newMountHost.trim(), container_path: newMountContainer.trim(), mode: newMountMode }] });
                          setNewMountHost(""); setNewMountContainer(""); setNewMountMode("rw");
                        }
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* Host panel */}
              {ws.type === "host" && (
                <div style={{ borderLeft: "2px solid #166534", paddingLeft: 12, display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Host Settings</div>
                  <FormRow label="Custom Root"><TextInput value={host.root || ""} onChangeText={(v) => setHost({ root: v })} placeholder="auto: ~/.agent-workspaces/<bot-id>/" /></FormRow>

                  {/* Commands */}
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Allowed Commands</div>
                    <div style={{ fontSize: 10, color: t.textDim, marginBottom: 4 }}>Use * to allow any. Leave subcommands empty for all.</div>
                    {commands.map((cmd: any, i: number) => (
                      <div key={i} style={rowStyle}>
                        <span style={{ fontFamily: "monospace", color: "#818cf8", minWidth: 50, maxWidth: 80, overflow: "hidden", textOverflow: "ellipsis" }}>{cmd.name}</span>
                        <span style={{ color: t.textMuted, flex: 1 }}>{cmd.subcommands?.length ? cmd.subcommands.join(", ") : "(all)"}</span>
                        {removeBtn(() => setHost({ commands: commands.filter((_: any, j: number) => j !== i) }))}
                      </div>
                    ))}
                    <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                      {miniInput(newCmd, setNewCmd, "binary", { flex: 1, maxWidth: 100 })}
                      {miniInput(newCmdSubs, setNewCmdSubs, "subcommands (comma-sep)", { flex: 1 })}
                      {addBtn("Add", () => {
                        if (newCmd.trim()) {
                          const subs = newCmdSubs.trim() ? newCmdSubs.split(",").map((s) => s.trim()).filter(Boolean) : [];
                          setHost({ commands: [...commands, { name: newCmd.trim(), subcommands: subs }] });
                          setNewCmd(""); setNewCmdSubs("");
                        }
                      })}
                    </div>
                  </div>

                  {/* Blocked patterns */}
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Blocked Patterns (regex)</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {blocked.map((pat, i) => (
                    <span key={i} style={{ display: "flex", alignItems: "center", gap: 4, background: t.inputBg, borderRadius: 4, padding: "2px 8px", fontSize: 11, fontFamily: "monospace", color: "#fbbf24" }}>
                      {pat} {removeBtn(() => setHost({ blocked_patterns: blocked.filter((_, j) => j !== i) }))}
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                  {miniInput(newBlocked, setNewBlocked, "regex pattern", { flex: 1 })}
                  {addBtn("Add", () => { if (newBlocked.trim()) { setHost({ blocked_patterns: [...blocked, newBlocked.trim()] }); setNewBlocked(""); } })}
                </div>
              </div>

              {/* Env passthrough */}
              <div>
                <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>Env Passthrough</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {envPass.map((v, i) => (
                    <span key={i} style={{ display: "flex", alignItems: "center", gap: 4, background: t.inputBg, borderRadius: 4, padding: "2px 8px", fontSize: 11, fontFamily: "monospace", color: "#93c5fd" }}>
                      {v} {removeBtn(() => setHost({ env_passthrough: envPass.filter((_, j) => j !== i) }))}
                    </span>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                  {miniInput(newEnvPass, setNewEnvPass, "ENV_VAR_NAME", { flex: 1, maxWidth: 200 })}
                  {addBtn("Add", () => { if (newEnvPass.trim()) { setHost({ env_passthrough: [...envPass, newEnvPass.trim()] }); setNewEnvPass(""); } })}
                </div>
              </div>
            </div>
          )}
            </>
          )}

          {/* Indexing panel */}
          <div style={{ borderTop: `1px solid ${t.surfaceRaised}`, paddingTop: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.05em" }}>Workspace Indexing</div>
              <Toggle value={indexing.enabled !== false} onChange={(v) => setIndexing({ enabled: v })} label="Enable" />
              {indexing.enabled !== false && (
                <Toggle value={indexing.watch !== false} onChange={(v) => setIndexing({ watch: v })} label="Watch" />
              )}
            </div>
            {indexing.enabled !== false && (
              <>
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>File Patterns</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {patterns.map((pat, i) => (
                      <span key={i} style={{ display: "flex", alignItems: "center", gap: 4, background: t.inputBg, borderRadius: 4, padding: "2px 8px", fontSize: 11, fontFamily: "monospace", color: "#93c5fd" }}>
                        {pat} {removeBtn(() => setIndexing({ patterns: patterns.filter((_, j) => j !== i) }))}
                      </span>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                    {miniInput(newPattern, setNewPattern, "**/*.py", { flex: 1, maxWidth: 200 })}
                    {addBtn("Add", () => { if (newPattern.trim()) { setIndexing({ patterns: [...patterns, newPattern.trim()] }); setNewPattern(""); } })}
                  </div>
                </div>
                <Row gap={12}>
                  <Col><FormRow label="Similarity Threshold"><TextInput value={String(indexing.similarity_threshold ?? "")} onChangeText={(v) => setIndexing({ similarity_threshold: v ? parseFloat(v) : null })} placeholder="server default" type="number" /></FormRow></Col>
                  <Col><FormRow label="Top-K Results"><TextInput value={String(indexing.top_k ?? "")} onChangeText={(v) => setIndexing({ top_k: v ? parseInt(v) : null })} placeholder="8" type="number" /></FormRow></Col>
                  <Col><FormRow label="Cooldown (sec)"><TextInput value={String(indexing.cooldown_seconds ?? "")} onChangeText={(v) => setIndexing({ cooldown_seconds: v ? parseInt(v) : null })} placeholder="300" type="number" /></FormRow></Col>
                  <Col><FormRow label="Embedding Model"><LlmModelDropdown value={indexing.embedding_model ?? ""} onChange={(v) => setIndexing({ embedding_model: v || null })} placeholder="server default" /></FormRow></Col>
                </Row>
                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, textTransform: "uppercase", marginBottom: 4 }}>
                    Index Segments
                    <span style={{ fontWeight: 400, color: t.textDim, textTransform: "none", marginLeft: 6 }}>per-path-prefix overrides</span>
                  </div>
                  {segments.map((seg: any, i: number) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 8px", background: t.inputBg, borderRadius: 4, fontSize: 11, marginBottom: 4 }}>
                      <span style={{ fontFamily: "monospace", color: "#93c5fd" }}>{seg.path_prefix}</span>
                      {seg.embedding_model && <span style={{ color: t.textMuted }}>model: <span style={{ color: "#a78bfa", fontFamily: "monospace" }}>{seg.embedding_model}</span></span>}
                      {seg.patterns && <span style={{ color: t.textDim }}>patterns: {seg.patterns.length}</span>}
                      {seg.similarity_threshold != null && <span style={{ color: t.textDim }}>thresh: {seg.similarity_threshold}</span>}
                      {seg.top_k != null && <span style={{ color: t.textDim }}>k: {seg.top_k}</span>}
                      {removeBtn(() => setIndexing({ segments: segments.filter((_: any, j: number) => j !== i) }))}
                    </div>
                  ))}
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                    {miniInput(newSegPrefix, setNewSegPrefix, "path_prefix (e.g. src/)", { flex: 1, minWidth: 80 })}
                    {miniInput(newSegModel, setNewSegModel, "embedding model (optional)", { flex: 1, minWidth: 80 })}
                    {addBtn("Add Segment", () => {
                      if (newSegPrefix.trim()) {
                        const seg: any = { path_prefix: newSegPrefix.trim() };
                        if (newSegModel.trim()) seg.embedding_model = newSegModel.trim();
                        setIndexing({ segments: [...segments, seg] });
                        setNewSegPrefix("");
                        setNewSegModel("");
                      }
                    })}
                  </div>
                </div>
              </>
            )}
          </div>
        </>
      )}

    </div>
  );
}
