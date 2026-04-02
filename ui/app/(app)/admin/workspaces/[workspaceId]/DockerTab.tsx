import { Plus, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  FormRow, TextInput, SelectInput, Toggle, Section, Row, Col,
} from "@/src/components/shared/FormControls";

// ---------------------------------------------------------------------------
// Env var editor
// ---------------------------------------------------------------------------
export function EnvEditor({ entries, onChange }: {
  entries: { key: string; value: string }[];
  onChange: (entries: { key: string; value: string }[]) => void;
}) {
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {entries.map((entry, i) => (
        <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            value={entry.key}
            onChange={(e) => {
              const next = [...entries];
              next[i] = { ...next[i], key: e.target.value };
              onChange(next);
            }}
            placeholder="KEY"
            style={{
              flex: 1, background: t.inputBg,
              border: `1px solid ${!entry.key ? t.dangerBorder : t.surfaceBorder}`,
              borderRadius: 6,
              padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <span style={{ color: t.textDim }}>=</span>
          <input
            value={entry.value}
            onChange={(e) => {
              const next = [...entries];
              next[i] = { ...next[i], value: e.target.value };
              onChange(next);
            }}
            placeholder="value"
            style={{
              flex: 2, background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
              padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
              outline: "none",
            }}
          />
          <button
            onClick={() => onChange(entries.filter((_, j) => j !== i))}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: t.textDim, padding: 2, flexShrink: 0,
            }}
          >
            <X size={14} />
          </button>
        </div>
      ))}
      <button
        onClick={() => onChange([...entries, { key: "", value: "" }])}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          padding: "4px 10px", fontSize: 11, fontWeight: 600,
          border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
          background: "transparent", color: t.textMuted, cursor: "pointer",
          alignSelf: "flex-start",
        }}
      >
        <Plus size={12} /> Add Variable
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Docker tab props
// ---------------------------------------------------------------------------
export interface DockerTabProps {
  image: string;
  setImage: (v: string) => void;
  network: string;
  setNetwork: (v: string) => void;
  dockerUser: string;
  setDockerUser: (v: string) => void;
  startupScript: string;
  setStartupScript: (v: string) => void;
  cpus: string;
  setCpus: (v: string) => void;
  memoryLimit: string;
  setMemoryLimit: (v: string) => void;
  readOnlyRoot: boolean;
  setReadOnlyRoot: (v: boolean) => void;
  env: { key: string; value: string }[];
  setEnv: (v: { key: string; value: string }[]) => void;
  ports: { host: string; container: string }[];
  setPorts: (v: { host: string; container: string }[]) => void;
  mounts: { host_path: string; container_path: string; mode: string }[];
  setMounts: (v: { host_path: string; container_path: string; mode: string }[]) => void;
}

// ---------------------------------------------------------------------------
// Docker tab
// ---------------------------------------------------------------------------
export function DockerTab({
  image, setImage,
  network, setNetwork,
  dockerUser, setDockerUser,
  startupScript, setStartupScript,
  cpus, setCpus,
  memoryLimit, setMemoryLimit,
  readOnlyRoot, setReadOnlyRoot,
  env, setEnv,
  ports, setPorts,
  mounts, setMounts,
}: DockerTabProps) {
  const t = useThemeTokens();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Docker Config */}
      <Section title="Docker Configuration">
        <FormRow label="Image" description="Docker image for the workspace container">
          <TextInput value={image} onChangeText={setImage} placeholder="agent-workspace:latest" />
        </FormRow>
        <Row>
          <Col>
            <FormRow label="Network">
              <SelectInput
                value={network}
                onChange={setNetwork}
                options={[
                  { label: "None", value: "none" },
                  { label: "Bridge", value: "bridge" },
                  { label: "Host", value: "host" },
                ]}
              />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Docker User" description="Run-as user inside container">
              <TextInput value={dockerUser} onChangeText={setDockerUser} placeholder="Default (root)" />
            </FormRow>
          </Col>
        </Row>
        <FormRow label="Startup Script" description="Script path executed on every container start/recreate. Leave empty to disable.">
          <TextInput value={startupScript} onChangeText={setStartupScript} placeholder="/workspace/startup.sh" />
        </FormRow>
      </Section>

      {/* Resources */}
      <Section title="Resources">
        <Row>
          <Col>
            <FormRow label="CPUs" description="CPU limit (e.g. 2.0)">
              <TextInput value={cpus} onChangeText={setCpus} placeholder="No limit" type="number" />
            </FormRow>
          </Col>
          <Col>
            <FormRow label="Memory Limit" description="e.g. 2g, 512m">
              <TextInput value={memoryLimit} onChangeText={setMemoryLimit} placeholder="No limit" />
            </FormRow>
          </Col>
        </Row>
        <Toggle
          value={readOnlyRoot}
          onChange={setReadOnlyRoot}
          label="Read-only root filesystem"
          description="/workspace is always writable. Other paths become read-only."
        />
      </Section>

      {/* Environment */}
      <Section title="Environment Variables" description="Injected into the container. AGENT_SERVER_URL and AGENT_SERVER_API_KEY are auto-injected.">
        <EnvEditor entries={env} onChange={setEnv} />
        <div style={{ fontSize: 11, color: t.textDim, marginTop: 8 }}>
          For sensitive values (API keys, tokens), use <a href="/admin/secret-values" style={{ color: t.accent }}>Secrets</a> instead — they are encrypted at rest and automatically redacted from tool results and LLM output.
        </div>
      </Section>

      {/* Port Mappings */}
      <Section title="Port Mappings" description="Map host ports to container ports">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {ports.map((p, i) => (
            <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                value={p.host}
                onChange={(e) => {
                  const next = [...ports];
                  next[i] = { ...next[i], host: e.target.value };
                  setPorts(next);
                }}
                placeholder="Host port"
                style={{
                  flex: 1, background: t.inputBg,
                  border: `1px solid ${!p.host && p.container ? t.dangerBorder : t.surfaceBorder}`,
                  borderRadius: 6,
                  padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
                  outline: "none",
                }}
              />
              <span style={{ color: t.textDim }}>:</span>
              <input
                value={p.container}
                onChange={(e) => {
                  const next = [...ports];
                  next[i] = { ...next[i], container: e.target.value };
                  setPorts(next);
                }}
                placeholder="Container port"
                style={{
                  flex: 1, background: t.inputBg,
                  border: `1px solid ${p.host && !p.container ? t.dangerBorder : t.surfaceBorder}`,
                  borderRadius: 6,
                  padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
                  outline: "none",
                }}
              />
              <button
                onClick={() => setPorts(ports.filter((_, j) => j !== i))}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: t.textDim, padding: 2, flexShrink: 0,
                }}
              >
                <X size={14} />
              </button>
            </div>
          ))}
          <button
            onClick={() => setPorts([...ports, { host: "", container: "" }])}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "4px 10px", fontSize: 11, fontWeight: 600,
              border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
              background: "transparent", color: t.textMuted, cursor: "pointer",
              alignSelf: "flex-start",
            }}
          >
            <Plus size={12} /> Add Port
          </button>
        </div>
      </Section>

      {/* Volume Mounts */}
      <Section title="Extra Mounts" description="/workspace is always mounted. Add additional host paths here.">
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {mounts.map((m, i) => (
            <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input
                value={m.host_path}
                onChange={(e) => {
                  const next = [...mounts];
                  next[i] = { ...next[i], host_path: e.target.value };
                  setMounts(next);
                }}
                placeholder="Host path"
                style={{
                  flex: 2, background: t.inputBg,
                  border: `1px solid ${!m.host_path && m.container_path ? t.dangerBorder : t.surfaceBorder}`,
                  borderRadius: 6,
                  padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
                  outline: "none",
                }}
              />
              <span style={{ color: t.textDim }}>{"\u2192"}</span>
              <input
                value={m.container_path}
                onChange={(e) => {
                  const next = [...mounts];
                  next[i] = { ...next[i], container_path: e.target.value };
                  setMounts(next);
                }}
                placeholder="Container path"
                style={{
                  flex: 2, background: t.inputBg,
                  border: `1px solid ${m.host_path && !m.container_path ? t.dangerBorder : t.surfaceBorder}`,
                  borderRadius: 6,
                  padding: "5px 8px", color: t.text, fontSize: 12, fontFamily: "monospace",
                  outline: "none",
                }}
              />
              <select
                value={m.mode}
                onChange={(e) => {
                  const next = [...mounts];
                  next[i] = { ...next[i], mode: e.target.value };
                  setMounts(next);
                }}
                style={{
                  background: t.inputBg, border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
                  padding: "3px 6px", color: t.text, fontSize: 11, cursor: "pointer",
                  outline: "none", flexShrink: 0,
                }}
              >
                <option value="rw">rw</option>
                <option value="ro">ro</option>
              </select>
              <button
                onClick={() => setMounts(mounts.filter((_, j) => j !== i))}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  color: t.textDim, padding: 2, flexShrink: 0,
                }}
              >
                <X size={14} />
              </button>
            </div>
          ))}
          <button
            onClick={() => setMounts([...mounts, { host_path: "", container_path: "", mode: "rw" }])}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "4px 10px", fontSize: 11, fontWeight: 600,
              border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
              background: "transparent", color: t.textMuted, cursor: "pointer",
              alignSelf: "flex-start",
            }}
          >
            <Plus size={12} /> Add Mount
          </button>
        </div>
      </Section>
    </div>
  );
}
