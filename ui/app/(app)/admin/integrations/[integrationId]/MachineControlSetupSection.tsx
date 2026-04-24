import { useEffect, useMemo, useState } from "react";
import { Copy, ExternalLink, Key, Monitor, RefreshCw, Trash2 } from "lucide-react";

import { useThemeTokens } from "@/src/theme/tokens";
import { writeToClipboard } from "@/src/utils/clipboard";
import {
  useIntegrationApiKey,
  useProvisionIntegrationApiKey,
  useRevokeIntegrationApiKey,
  type IntegrationMachineControlInfo,
} from "@/src/api/hooks/useIntegrations";
import { useAdminMachines, useEnrollMachineTarget } from "@/src/api/hooks/useMachineTargets";
import { buildRemoteEnrollCommand, resolveMachineControlServerUrl } from "@/src/lib/machineControlSetup";
import {
  MachineEnrollFields,
  buildMachineEnrollDraft,
  normalizeMachineEnrollConfig,
  type MachineEnrollDraft,
} from "@/src/components/machineControl/MachineEnrollFields";

function CopyButton({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  const t = useThemeTokens();
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await writeToClipboard(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        borderRadius: 6,
        border: `1px solid ${t.surfaceBorder}`,
        background: "transparent",
        color: copied ? t.success : t.text,
        padding: "6px 10px",
        fontSize: 12,
        fontWeight: 600,
      }}
    >
      <Copy size={12} />
      {copied ? "Copied" : label}
    </button>
  );
}

export function MachineControlSetupSection({
  integrationId,
  machineControl,
  enableRemoteProvisioning,
}: {
  integrationId: string;
  machineControl: IntegrationMachineControlInfo;
  enableRemoteProvisioning: boolean;
}) {
  const t = useThemeTokens();
  const serverUrl = resolveMachineControlServerUrl(
    typeof window !== "undefined" ? window.location.origin : "",
  );
  const { data: machineData } = useAdminMachines(true);
  const enroll = useEnrollMachineTarget(machineControl.provider_id);
  const provider = useMemo(
    () => machineData?.providers.find((item) => item.provider_id === machineControl.provider_id) ?? null,
    [machineData, machineControl.provider_id],
  );
  const [labelDraft, setLabelDraft] = useState("");
  const enrollFields = provider?.enroll_fields ?? machineControl.enroll_fields ?? [];
  const [configDraft, setConfigDraft] = useState<MachineEnrollDraft>(() => buildMachineEnrollDraft(enrollFields));
  const launch = enroll.data?.launch ?? null;
  const enrolledTarget = enroll.data?.target ?? null;
  const configReady = provider?.config_ready ?? true;
  const readyCount = provider?.ready_target_count ?? provider?.connected_target_count ?? 0;

  const apiKey = useIntegrationApiKey(integrationId, enableRemoteProvisioning);
  const provisionApiKey = useProvisionIntegrationApiKey(integrationId);
  const revokeApiKey = useRevokeIntegrationApiKey(integrationId);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const displayKey = revealedKey ?? provisionApiKey.data?.key_value ?? null;
  const config = normalizeMachineEnrollConfig(enrollFields, configDraft);
  const remoteCommand = displayKey && serverUrl
    ? buildRemoteEnrollCommand({
        serverUrl,
        providerId: machineControl.provider_id,
        apiKey: displayKey,
        label: labelDraft,
        config,
      })
    : "";

  useEffect(() => {
    setConfigDraft(buildMachineEnrollDraft(enrollFields));
  }, [provider?.provider_id, JSON.stringify(enrollFields)]);

  function handleProvisionKey() {
    setRevealedKey(null);
    provisionApiKey.mutate(undefined, {
      onSuccess: (result) => {
        if (result.key_value) setRevealedKey(result.key_value);
      },
    });
  }

  function handleConfigChange(key: string, value: string | boolean) {
    setConfigDraft((current) => ({ ...current, [key]: value }));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 12, color: t.textDim, lineHeight: "18px" }}>
        This provider plugs into the core machine-control center. Enroll targets here or in
        {" "}
        <a href="/admin/machines" style={{ color: t.accent, textDecoration: "none" }}>Admin &gt; Machines</a>
        ; chat still owns leases.
      </div>

      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
        }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 8px",
            borderRadius: 6,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            fontSize: 11,
            color: t.textDim,
          }}
        >
          <Monitor size={12} />
          Driver: {machineControl.driver}
        </span>
        {provider ? (
          <span
            style={{
              fontSize: 11,
              color: t.textDim,
            }}
          >
            {readyCount}/{provider.target_count} ready
          </span>
        ) : null}
        <a
          href="/admin/machines"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 11,
            fontWeight: 600,
            color: t.accent,
            textDecoration: "none",
            marginLeft: "auto",
          }}
        >
          Open machine center
          <ExternalLink size={12} />
        </a>
      </div>

      {!configReady ? (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surfaceRaised,
            fontSize: 12,
            color: t.textDim,
          }}
        >
          Provider setup is incomplete. Fill in the required settings above, then come back to enroll targets.
        </div>
      ) : null}

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 10,
          padding: 12,
          borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.surfaceRaised,
        }}
      >
        <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: t.textDim }}>Label</span>
          <input
            value={labelDraft}
            onChange={(event) => setLabelDraft(event.target.value)}
            placeholder="Optional machine label"
            style={{
              minHeight: 36,
              borderRadius: 6,
              border: `1px solid ${t.inputBorder}`,
              background: t.inputBg,
              color: t.text,
              padding: "8px 10px",
              fontSize: 12,
            }}
          />
        </label>
        <MachineEnrollFields
          fields={enrollFields}
          draft={configDraft}
          onChange={handleConfigChange}
          disabled={enroll.isPending || !configReady}
          t={t}
        />
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ fontSize: 11, color: t.textDim }}>
            {enrollFields.length
              ? "Fill in the provider-specific target details, then enroll the machine."
              : "Enroll a new machine target for this provider."}
          </div>
          <button
            type="button"
            onClick={() => enroll.mutate({ label: labelDraft || null, config })}
            disabled={enroll.isPending || !configReady}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              borderRadius: 6,
              border: `1px solid ${t.accentBorder}`,
              background: t.accentSubtle,
              color: t.accent,
              padding: "8px 12px",
              fontSize: 12,
              fontWeight: 700,
              opacity: enroll.isPending || !configReady ? 0.7 : 1,
            }}
          >
            <Monitor size={14} />
            {enroll.isPending ? "Enrolling..." : "Enroll target"}
          </button>
        </div>
      </div>

      {launch?.example_command ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: 12,
            borderRadius: 8,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.surfaceRaised,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Launch command</span>
              <span style={{ fontSize: 11, color: t.textDim }}>
                {enrolledTarget?.label || machineControl.label}
                {enrolledTarget?.target_id ? ` · ${enrolledTarget.target_id}` : ""}
              </span>
            </div>
            <CopyButton label="Copy command" value={launch.example_command} />
          </div>
          <code
            style={{
              display: "block",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontSize: 12,
              color: t.text,
            }}
          >
            {launch.example_command}
          </code>
          <div style={{ fontSize: 11, color: t.textDim }}>
            Run that on the target machine to finish provider-specific setup for this enrolled target.
          </div>
        </div>
      ) : null}

      {enableRemoteProvisioning ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: 12,
            borderRadius: 8,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.inputBg,
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <span style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Remote enroll helper</span>
              <span style={{ fontSize: 11, color: t.textDim }}>
                Generate a scoped key and copy a ready curl for enrolling this provider from another terminal or host.
              </span>
            </div>
            {!apiKey.data?.provisioned && !displayKey ? (
              <button
                type="button"
                onClick={handleProvisionKey}
                disabled={provisionApiKey.isPending}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  borderRadius: 6,
                  border: "none",
                  background: t.accent,
                  color: "#fff",
                  padding: "6px 12px",
                  fontSize: 12,
                  fontWeight: 700,
                  opacity: provisionApiKey.isPending ? 0.7 : 1,
                }}
              >
                <Key size={12} />
                {provisionApiKey.isPending ? "Generating..." : "Generate Setup Key"}
              </button>
            ) : (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={handleProvisionKey}
                  disabled={provisionApiKey.isPending}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    borderRadius: 6,
                    border: `1px solid ${t.surfaceBorder}`,
                    background: "transparent",
                    color: t.text,
                    padding: "6px 10px",
                    fontSize: 12,
                    fontWeight: 600,
                  }}
                >
                  <RefreshCw size={12} />
                  Reveal New Key
                </button>
                <button
                  type="button"
                  onClick={() => revokeApiKey.mutate()}
                  disabled={revokeApiKey.isPending}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    borderRadius: 6,
                    border: `1px solid ${t.danger}`,
                    background: t.dangerSubtle,
                    color: t.danger,
                    padding: "6px 10px",
                    fontSize: 12,
                    fontWeight: 600,
                  }}
                >
                  <Trash2 size={12} />
                  Revoke
                </button>
              </div>
            )}
          </div>

          {displayKey ? (
            <>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                  padding: 10,
                  borderRadius: 8,
                  border: "1px solid rgba(234,179,8,0.2)",
                  background: "rgba(234,179,8,0.08)",
                }}
              >
                <div style={{ fontSize: 11, color: t.textDim }}>
                  Full key is only shown now. Copy it before leaving this page.
                </div>
                <code style={{ fontSize: 11, color: t.text, wordBreak: "break-all" }}>{displayKey}</code>
                <div>
                  <CopyButton label="Copy key" value={displayKey} />
                </div>
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <code
                  style={{
                    display: "block",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    fontSize: 12,
                    color: t.text,
                    padding: 10,
                    borderRadius: 8,
                    border: `1px solid ${t.surfaceBorder}`,
                    background: t.surfaceRaised,
                  }}
                >
                  {remoteCommand}
                </code>
                <div>
                  <CopyButton label="Copy curl" value={remoteCommand} />
                </div>
              </div>
            </>
          ) : apiKey.data?.provisioned ? (
            <div style={{ fontSize: 11, color: t.textDim }}>
              A setup key already exists ({apiKey.data.key_prefix}...). Regenerate it here if you need the full value again.
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
