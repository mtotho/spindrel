import { useCallback, useEffect, useRef, useState } from "react";
import yaml from "js-yaml";
import { AlertTriangle, CheckCircle, Copy, RefreshCw, Server, XCircle } from "lucide-react";

import { Spinner } from "@/src/components/shared/Spinner";
import {
  useIntegrationManifest,
  useIntegrationYaml,
  useUpdateIntegrationYaml,
} from "@/src/api/hooks/useIntegrations";
import { useTestMCPServer } from "@/src/api/hooks/useMCPServers";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  ActionButton,
  InfoBanner,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSegmentedControl,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

type ViewMode = "visual" | "yaml";

interface MCPServerInfo {
  id: string;
  display_name?: string;
  url?: string;
  image?: string;
  port?: number;
  connected?: boolean;
  url_configured?: boolean;
}

function MCPServerCard({ server }: { server: MCPServerInfo }) {
  const [copied, setCopied] = useState(false);
  const testMut = useTestMCPServer();
  const connected = Boolean(server.connected);
  const needsSetup = Boolean(server.image && !server.url);
  const dockerCmd = server.image
    ? `docker run -d --name spindrel-mcp-${server.id} -p ${server.port || 3000}:${server.port || 3000} ${server.image}`
    : null;

  const handleCopyCmd = async () => {
    if (!dockerCmd) return;
    await writeToClipboard(dockerCmd);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <SettingsControlRow
      leading={<Server size={14} />}
      title={server.display_name || server.id}
      description={
        <span className="space-y-1">
          {server.url && <span className="block break-all font-mono">{server.url}</span>}
          {needsSetup && dockerCmd && (
            <span className="block rounded-md bg-surface-overlay/35 px-2 py-1 font-mono text-[10px] text-text-muted">
              {dockerCmd}
            </span>
          )}
        </span>
      }
      meta={
        <StatusBadge
          label={connected ? "Connected" : needsSetup ? "Setup required" : "Disconnected"}
          variant={connected ? "success" : needsSetup ? "warning" : "danger"}
        />
      }
      action={
        <div className="flex flex-wrap items-center gap-1.5">
          {dockerCmd && (
            <ActionButton
              label={copied ? "Copied" : "Copy command"}
              onPress={() => void handleCopyCmd()}
              variant="secondary"
              size="small"
              icon={<Copy size={12} />}
            />
          )}
          <ActionButton
            label={testMut.isPending ? "Testing..." : "Test"}
            onPress={() => testMut.mutate(server.id)}
            disabled={testMut.isPending || !server.url}
            variant="secondary"
            size="small"
            icon={<RefreshCw size={12} />}
          />
          {testMut.isSuccess && <CheckCircle size={13} className="text-success" />}
          {testMut.isError && <XCircle size={13} className="text-danger" />}
        </div>
      }
    />
  );
}

function YamlEditorTab({ integrationId }: { integrationId: string }) {
  const { data, isLoading } = useIntegrationYaml(integrationId);
  const updateMut = useUpdateIntegrationYaml(integrationId);
  const [draft, setDraft] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const prevIdRef = useRef(integrationId);
  const validateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (prevIdRef.current !== integrationId) {
      prevIdRef.current = integrationId;
      setDraft("");
      setParseError(null);
      setSaved(false);
    }
    if (data?.yaml && draft === "") setDraft(data.yaml);
  }, [data, integrationId, draft]);

  const handleChange = useCallback((text: string) => {
    setDraft(text);
    setSaved(false);
    if (validateTimer.current) clearTimeout(validateTimer.current);
    validateTimer.current = setTimeout(() => {
      try {
        yaml.load(text);
        setParseError(null);
      } catch (error: any) {
        setParseError(error.message || "Invalid YAML");
      }
    }, 300);
  }, []);

  const handleSave = useCallback(() => {
    if (parseError) return;
    updateMut.mutate(draft, {
      onSuccess: () => {
        setSaved(true);
        window.setTimeout(() => setSaved(false), 2000);
      },
    });
  }, [draft, parseError, updateMut]);

  if (isLoading) {
    return (
      <div className="flex min-h-[120px] items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton
          label={updateMut.isPending ? "Saving..." : "Save YAML"}
          onPress={handleSave}
          disabled={Boolean(parseError) || updateMut.isPending}
          size="small"
        />
        {saved && <StatusBadge label="Saved" variant="success" />}
        {updateMut.isError && <StatusBadge label="Failed to save" variant="danger" />}
      </div>
      {parseError && (
        <InfoBanner variant="danger" icon={<AlertTriangle size={14} />}>
          {parseError}
        </InfoBanner>
      )}
      <textarea
        value={draft}
        onChange={(event) => handleChange(event.target.value)}
        spellCheck={false}
        className="min-h-[500px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 font-mono text-[12px] leading-relaxed text-text outline-none focus:border-accent focus:ring-2 focus:ring-accent/35"
      />
    </div>
  );
}

export function ManifestEditor({ integrationId }: { integrationId: string }) {
  const [mode, setMode] = useState<ViewMode>("visual");
  const { data: manifestData } = useIntegrationManifest(integrationId);
  const manifest = manifestData?.manifest;
  const mcpServers = (manifest?.mcp_servers as MCPServerInfo[] | undefined) ?? [];
  const fileDrift = manifest?._file_drift as { drifted: boolean; reason: string } | undefined;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <SettingsSegmentedControl
          value={mode}
          onChange={setMode}
          options={[
            { value: "visual", label: "Visual" },
            { value: "yaml", label: "YAML" },
          ]}
        />
        {fileDrift?.drifted && (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-warning-muted">
            <AlertTriangle size={12} />
            Source file changed on disk
          </span>
        )}
      </div>

      {mode === "visual" ? (
        <div className="flex flex-col gap-2">
          {mcpServers.length > 0 ? (
            <>
              <SettingsGroupLabel label="MCP Servers" count={mcpServers.length} />
              <div className="flex flex-col gap-1.5">
                {mcpServers.map((server) => <MCPServerCard key={server.id} server={server} />)}
              </div>
            </>
          ) : (
            <div className="text-[12px] text-text-dim">No visual manifest sections are available for this integration.</div>
          )}
        </div>
      ) : (
        <YamlEditorTab integrationId={integrationId} />
      )}
    </div>
  );
}
