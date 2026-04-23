import type {
  ToolResultEnvelope,
  WidgetDashboardPin,
  WidgetLibraryEntry,
} from "@/src/types/api";

const HTML_INTERACTIVE_CT = "application/vnd.spindrel.html+interactive";
const NATIVE_APP_CT = "application/vnd.spindrel.native-app+json";

interface ContractField {
  label: string;
  value: string;
}

function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

function joinList(values: string[]): string {
  return values.length > 0 ? values.join(", ") : "None declared";
}

function summarizeActionIds(
  actions:
    | Array<{ id: string }>
    | null
    | undefined,
): string {
  return joinList((actions ?? []).map((action) => action.id));
}

function summarizeThemeSupport(themeSupport?: WidgetLibraryEntry["theme_support"]): string {
  if (themeSupport === "html") return "HTML theme hooks available";
  if (themeSupport === "template") return "Component/template theme path";
  return "No widget-specific theme contract declared";
}

function runtimeKindFromEnvelope(envelope: ToolResultEnvelope): "html" | "template" | "native_app" {
  if (envelope.content_type === NATIVE_APP_CT) return "native_app";
  if (envelope.content_type === HTML_INTERACTIVE_CT) return "html";
  return "template";
}

function runtimeLabel(kind: "html" | "template" | "native_app"): string {
  if (kind === "native_app") return "Native widget";
  if (kind === "html") return "HTML widget";
  return "Tool renderer widget";
}

function authLabelForLibraryEntry(
  entry: WidgetLibraryEntry,
  effectiveBotId: string | null,
): string {
  if (entry.widget_kind === "native_app") {
    return "Host-owned actions via the native widget registry; no iframe bot token.";
  }
  if (entry.widget_kind === "template") {
    return "Server-side tool actions/polls run with the pin's stored bot and channel context.";
  }
  if (effectiveBotId) {
    return "Widget SDK calls run as the selected/source bot when the widget uses the API.";
  }
  return "Needs a source bot for bot-scoped API access; static HTML can still render without one.";
}

function authoringLabelForLibraryEntry(entry: WidgetLibraryEntry): string {
  if (entry.widget_kind === "native_app") {
    return "Core-only. Users can place and invoke it, but only the app ships native widgets.";
  }
  if (entry.widget_kind === "template") {
    return "Tool-bound renderer. Authored once, then instantiated from a tool call or preset.";
  }
  if (entry.scope === "bot" || entry.scope === "workspace" || entry.scope === "channel") {
    return "User- or bot-authored HTML bundle discoverable directly from the library.";
  }
  return "Reusable HTML bundle shipped by the app or an integration.";
}

function stateLabelForLibraryEntry(entry: WidgetLibraryEntry): string {
  if (entry.widget_kind === "native_app") {
    return "widget_instances.state is authoritative; the pin envelope is only cached presentation.";
  }
  if (entry.widget_kind === "template") {
    return "Tool output plus per-pin widget_config are authoritative.";
  }
  return "Widget-owned. JS/files/suite storage own live state; the host stores pin metadata and cached envelope data.";
}

function refreshLabelForLibraryEntry(entry: WidgetLibraryEntry): string {
  if (entry.widget_kind === "native_app") {
    return "Refresh comes from instance reloads and action results, not template state_poll.";
  }
  if (entry.widget_kind === "template") {
    return "Tool renderer widgets use state_poll when declared; otherwise they are snapshots.";
  }
  return "HTML widgets refresh through their own JS, source edits, or action-driven rerenders.";
}

function contextLabel(
  botId: string | null,
  channelId: string | null,
  botNameById?: Map<string, string>,
): string {
  const parts: string[] = [];
  if (botId) {
    const botName = botNameById?.get(botId);
    parts.push(`Bot: ${botName ? `@${botName}` : botId}`);
  }
  if (channelId) parts.push(`Channel: ${channelId}`);
  return parts.length > 0 ? parts.join(" | ") : "No bot or channel context stored on this pin.";
}

function authLabelForPin(
  kind: "html" | "template" | "native_app",
  pin: WidgetDashboardPin,
  botNameById?: Map<string, string>,
): string {
  if (kind === "native_app") {
    return "Host-owned native actions. The widget does not mint an iframe token.";
  }
  if (kind === "template") {
    return "Server-side actions and polls run with this pin's stored bot/channel context.";
  }
  if (pin.source_bot_id) {
    const botName = botNameById?.get(pin.source_bot_id);
    return `Widget SDK calls authenticate as ${botName ? `@${botName}` : "the pin's source bot"}.`;
  }
  return "No source bot stored. HTML API helpers will fail until the pin runs under a bot scope.";
}

function stateLabelForPin(kind: "html" | "template" | "native_app"): string {
  if (kind === "native_app") {
    return "widget_instances.state is authoritative; the pin envelope is cached output.";
  }
  if (kind === "template") {
    return "Server-side tool output plus widget_config are authoritative.";
  }
  return "Widget-owned. HTML runtime state lives inside the widget bundle and its storage.";
}

function refreshLabelForEnvelope(
  kind: "html" | "template" | "native_app",
  envelope: ToolResultEnvelope,
): string {
  if (kind === "native_app") {
    return "Action responses and instance reloads refresh the widget.";
  }
  if (kind === "template") {
    if (envelope.refreshable && envelope.refresh_interval_seconds) {
      return `state_poll refreshes every ${envelope.refresh_interval_seconds}s.`;
    }
    if (envelope.refreshable) {
      return "Refreshable template widget via state_poll.";
    }
    return "Snapshot until a new tool result or action updates it.";
  }
  if (envelope.source_path) {
    return "File-backed HTML widget; source edits and widget JS can both drive updates.";
  }
  return "Widget-owned refresh via its own JS or action-driven rerenders.";
}

function themeLabelForPin(kind: "html" | "template" | "native_app"): string {
  if (kind === "native_app") return "Uses app-native host theme tokens only.";
  if (kind === "template") return "Uses the component renderer and host theme tokens.";
  return "HTML theme hooks are available when the bundle opts into them.";
}

function envelopeNativeActions(
  envelope: ToolResultEnvelope,
): Array<{ id: string }> {
  if (envelope.content_type !== NATIVE_APP_CT) return [];
  const body = envelope.body;
  if (!body || typeof body !== "object" || Array.isArray(body)) return [];
  const actions = (body as { actions?: Array<{ id: string }> }).actions;
  return Array.isArray(actions) ? actions : [];
}

export function describeLibraryContract(
  entry: WidgetLibraryEntry,
  effectiveBotId: string | null,
): ContractField[] {
  return [
    { label: "Runtime", value: runtimeLabel(entry.widget_kind ?? "html") },
    { label: "Authoring", value: authoringLabelForLibraryEntry(entry) },
    { label: "Auth", value: authLabelForLibraryEntry(entry, effectiveBotId) },
    { label: "State", value: stateLabelForLibraryEntry(entry) },
    { label: "Refresh", value: refreshLabelForLibraryEntry(entry) },
    { label: "Theme", value: summarizeThemeSupport(entry.theme_support) },
    {
      label: "Supported scopes",
      value: entry.supported_scopes && entry.supported_scopes.length > 0
        ? entry.supported_scopes.map(titleCase).join(", ")
        : "No explicit scope restrictions declared",
    },
    { label: "Actions", value: summarizeActionIds(entry.actions) },
  ];
}

export function describePinContract(
  pin: WidgetDashboardPin,
  botNameById?: Map<string, string>,
): ContractField[] {
  const kind = runtimeKindFromEnvelope(pin.envelope);
  const actions = pin.available_actions && pin.available_actions.length > 0
    ? pin.available_actions
    : envelopeNativeActions(pin.envelope);
  return [
    { label: "Runtime", value: runtimeLabel(kind) },
    {
      label: "Pin context",
      value: contextLabel(pin.source_bot_id, pin.source_channel_id, botNameById),
    },
    { label: "Auth", value: authLabelForPin(kind, pin, botNameById) },
    { label: "State", value: stateLabelForPin(kind) },
    { label: "Refresh", value: refreshLabelForEnvelope(kind, pin.envelope) },
    { label: "Theme", value: themeLabelForPin(kind) },
    { label: "Actions", value: summarizeActionIds(actions) },
  ];
}

export function WidgetContractCard({
  fields,
  title = "Contract",
}: {
  fields: ContractField[];
  title?: string;
}) {
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
        {title}
      </div>
      <div className="mt-2 space-y-2">
        {fields.map((field) => (
          <div
            key={field.label}
            className="grid grid-cols-[92px_minmax(0,1fr)] items-start gap-2 text-[11px]"
          >
            <div className="font-semibold uppercase tracking-wide text-text-dim">
              {field.label}
            </div>
            <div className="leading-snug text-text-muted">
              {field.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
