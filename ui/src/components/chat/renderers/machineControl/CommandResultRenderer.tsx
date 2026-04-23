import type { RichResultViewProps } from "../../RichToolResult";
import {
  coerceCommandResultPayload,
  formatMachineDuration,
  machineCardStyle,
  machineMetaTextStyle,
} from "./shared";

export function CommandResultRenderer({
  data,
  t,
}: RichResultViewProps) {
  const payload = coerceCommandResultPayload(data);
  const stdout = payload.stdout ?? "";
  const stderr = payload.stderr ?? "";
  const hasOutput = Boolean(stdout.trim() || stderr.trim());
  const metaItems = [
    payload.provider_label || payload.provider_id,
    payload.target_label || payload.target_id,
    payload.working_dir ? `cwd ${payload.working_dir}` : null,
    typeof payload.exit_code === "number" ? `exit ${payload.exit_code}` : null,
    formatMachineDuration(payload.duration_ms),
    payload.truncated ? "truncated" : null,
  ].filter(Boolean);

  function outputBlock(label: string, content: string, tone: "default" | "danger" = "default") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: 11, color: tone === "danger" ? t.danger : t.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>
          {label}
        </div>
        <pre
          style={{
            margin: 0,
            padding: 10,
            borderRadius: 8,
            border: `1px solid ${t.surfaceBorder}`,
            background: t.inputBg,
            color: tone === "danger" ? t.danger : t.text,
            fontSize: 12,
            lineHeight: "18px",
            overflowX: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontFamily: "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace",
          }}
        >
          {content}
        </pre>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={machineCardStyle(t)}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <div style={{ fontWeight: 700, color: t.text }}>
            {payload.command || "Command"}
          </div>
          {metaItems.length ? (
            <div style={machineMetaTextStyle(t)}>
              {metaItems.join(" · ")}
            </div>
          ) : null}
        </div>
      </div>
      {stdout ? outputBlock("Stdout", stdout) : null}
      {stderr ? outputBlock("Stderr", stderr, "danger") : null}
      {!hasOutput ? (
        <div style={{ ...machineCardStyle(t), fontSize: 11, color: t.textDim }}>
          Command completed with no output.
        </div>
      ) : null}
    </div>
  );
}

export function renderCommandResultView(props: RichResultViewProps) {
  return <CommandResultRenderer {...props} />;
}
