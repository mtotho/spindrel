// Secret check types
export interface SecretCheckResult {
  has_secrets: boolean;
  exact_matches: number;
  pattern_matches: Array<{
    type: string;
  }>;
}

// Bot types
export interface MemoryConfig {
  enabled?: boolean;
  cross_channel?: boolean;
  cross_client?: boolean;
  cross_bot?: boolean;
  prompt?: string;
  similarity_threshold?: number;
}

export interface SkillConfig {
  id: string;
  mode?: string;
}

export interface BotConfig {
  id: string;
  name: string;
  model: string;
  system_prompt?: string;
  model_provider_id?: string | null;
  fallback_models?: Array<{ model: string; provider_id?: string | null }>;
  display_name?: string;
  avatar_url?: string;
  avatar_emoji?: string | null;
  local_tools?: string[];
  mcp_servers?: string[];
  client_tools?: string[];
  pinned_tools?: string[];
  skills?: SkillConfig[];
  tool_retrieval?: boolean;
  tool_discovery?: boolean;
  tool_similarity_threshold?: number | null;
  max_iterations?: number | null;
  max_script_tool_calls?: number | null;
  tool_result_config?: Record<string, any>;
  persona?: boolean;
  persona_content?: string;
  persona_from_workspace?: boolean;
  workspace_persona_content?: string | null;
  context_compaction?: boolean;
  compaction_interval?: number | null;
  compaction_keep_turns?: number | null;
  compaction_model?: string | null;
  compaction_model_provider_id?: string | null;
  history_mode?: string | null;
  audio_input?: string;
  memory?: MemoryConfig;
  memory_max_inject_chars?: number | null;
  delegate_bots?: string[];
  integration_config?: Record<string, any>;
  workspace?: Record<string, any>;
  docker_sandbox_profiles?: string[];
  model_params?: Record<string, any>;
  delegation_config?: Record<string, any>;
  user_id?: string | null;
  shared_workspace_id?: string | null;
  shared_workspace_role?: string | null;
  attachment_summarization_enabled?: boolean | null;
  attachment_summary_model?: string | null;
  attachment_summary_model_provider_id?: string | null;
  attachment_text_max_chars?: number | null;
  attachment_vision_concurrency?: number | null;
  api_permissions?: string[] | null;
  memory_scheme?: string | null;  // "workspace-files"|null
  memory_hygiene_enabled?: boolean | null;
  memory_hygiene_interval_hours?: number | null;
  memory_hygiene_prompt?: string | null;
  memory_hygiene_only_if_active?: boolean | null;
  memory_hygiene_model?: string | null;
  memory_hygiene_model_provider_id?: string | null;
  memory_hygiene_target_hour?: number | null;
  memory_hygiene_extra_instructions?: string | null;
  skill_review_enabled?: boolean | null;
  skill_review_interval_hours?: number | null;
  skill_review_prompt?: string | null;
  skill_review_only_if_active?: boolean | null;
  skill_review_model?: string | null;
  skill_review_model_provider_id?: string | null;
  skill_review_target_hour?: number | null;
  skill_review_extra_instructions?: string | null;
  system_prompt_workspace_file?: boolean;
  system_prompt_write_protected?: boolean;
  source_type?: string;  // "system"|"file"|"manual"
  // Agent harness — when set, this bot delegates its turn to an external
  // harness (Claude Code, ...) instead of running the RAG loop. See
  // docs/guides/agent-harnesses.md.
  harness_runtime?: string | null;
  harness_workdir?: string | null;
  harness_session_state?: Record<string, any> | null;
  created_at?: string;
  updated_at?: string;
}

// Workflows
export interface Workflow {
  id: string;
  name: string;
  description?: string | null;
  params: Record<string, any>;
  secrets: string[];
  defaults: Record<string, any>;
  steps: WorkflowStep[];
  triggers: Record<string, boolean>;
  tags: string[];
  session_mode: string;
  source_type: string;
  source_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowStep {
  id: string;
  type?: 'agent' | 'tool' | 'exec';
  prompt?: string;
  tool_name?: string;
  tool_args?: Record<string, any>;
  working_directory?: string;
  args?: string[];
  when?: Record<string, any> | null;
  requires_approval?: boolean;
  on_failure?: string;
  secrets?: string[];
  tools?: string[];
  model?: string | null;
  timeout?: number | null;
  inject_prior_results?: boolean;
  prior_result_max_chars?: number | null;
  result_max_chars?: number | null;
}

export interface WorkflowRun {
  id: string;
  workflow_id: string;
  bot_id: string;
  channel_id?: string | null;
  session_id?: string | null;
  params: Record<string, any>;
  status: string;
  current_step_index: number;
  step_states: WorkflowStepState[];
  dispatch_type: string;
  dispatch_config?: Record<string, any> | null;
  triggered_by?: string | null;
  session_mode: string;
  error?: string | null;
  workflow_snapshot?: Record<string, any> | null;
  created_at: string;
  completed_at?: string | null;
}

export interface WorkflowStepState {
  status: string;
  task_id?: string | null;
  result?: string | null;
  error?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  correlation_id?: string | null;
  retry_count?: number;
}

export interface WorkflowConnection {
  type: "heartbeat" | "scheduled_task";
  workflow_id: string;
  // heartbeat fields
  enabled?: boolean;
  interval_minutes?: number;
  // scheduled_task fields
  task_id?: string;
  workflow_session_mode?: string | null;
  recurrence?: string | null;
  status?: string;
  title?: string | null;
  bot_id?: string;
  scheduled_at?: string | null;
}

// Tool group from editor data
export interface ToolPack {
  pack: string;
  label: string;
  group?: string | null;
  warning?: string | null;
  tools: { name: string; description?: string | null }[];
}

export interface ToolGroup {
  integration: string;
  is_core: boolean;
  packs: ToolPack[];
  total: number;
}

export interface SkillOption {
  id: string;
  name: string;
  description?: string;
  source_type?: string;
  skill_layout?: "loose" | "folder_root" | "child";
  folder_root_id?: string | null;
  parent_skill_id?: string | null;
  has_children?: boolean;
}

export interface ModelParamDefinition {
  name: string;
  label: string;
  description: string;
  type: "slider" | "number" | "select";
  min?: number;
  max?: number;
  step?: number;
  default: number | string | null;
  options?: string[];
}

export interface ResolvedToolEntry {
  name: string;
  source: string;
  source_label: string;
  integration: string;
}

export interface ResolvedPreview {
  tools: ResolvedToolEntry[];
  pinned_tools: ResolvedToolEntry[];
  mcp_servers: ResolvedToolEntry[];
}

export interface BotEditorData {
  bot: BotConfig;
  default_shared_workspace_id?: string | null;
  default_shared_workspace_name?: string | null;
  tool_groups: ToolGroup[];
  mcp_servers: string[];
  client_tools: string[];
  all_skills: SkillOption[];
  all_bots: { id: string; name: string }[];
  all_sandbox_profiles: { name: string; description?: string }[];
  model_param_definitions: ModelParamDefinition[];
  model_param_support: Record<string, string[]>;
  reasoning_capable_models?: string[];
  resolved_preview?: ResolvedPreview | null;
  starter_skill_ids?: string[];
}

// Integration binding
export interface IntegrationBinding {
  id: string;
  channel_id: string;
  integration_type: string;
  client_id: string;
  dispatch_config?: Record<string, any> | null;
  display_name?: string | null;
  created_at: string;
  updated_at: string;
}

// Integration activation
export interface ConfigField {
  key: string;
  type: "string" | "boolean" | "number" | "select" | "multiselect" | "browse";
  label: string;
  description?: string;
  default?: any;
  options?: { value: string; label: string }[];
  source_integration?: string;
  browse_endpoint?: string;
}

export interface ActivatableIntegration {
  integration_type: string;
  description: string;
  requires_workspace: boolean;
  activated: boolean;
  tools: string[];
  has_system_prompt: boolean;
  version?: string | null;
  includes: string[];
  activation_config?: Record<string, any>;
  config_fields?: ConfigField[];
  included_by?: string[];
}

export interface ActivationResult {
  integration_type: string;
  activated: boolean;
  manifest?: Record<string, any> | null;
  warnings: Array<{ code: string; message: string }>;
}

export interface ChannelBotMemberConfig {
  max_rounds?: number | null;
  auto_respond?: boolean;
  response_style?: "brief" | "normal" | "detailed" | null;
  system_prompt_addon?: string | null;
  model_override?: string | null;
  priority?: number;
}

export interface ChannelBotMember {
  id: string;
  channel_id: string;
  bot_id: string;
  bot_name?: string;
  config: ChannelBotMemberConfig;
  created_at: string;
}

// Channel types (matches server ChannelOut)
export interface Channel {
  id: string;
  name: string;
  bot_id: string;
  client_id?: string;
  integration?: string;
  active_session_id?: string;
  require_mention: boolean;
  passive_memory: boolean;
  private: boolean;
  protected?: boolean;
  user_id?: string;
  display_name?: string;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  integrations?: IntegrationBinding[];
  member_bots?: ChannelBotMember[];
  heartbeat_enabled?: boolean;
  heartbeat_in_quiet_hours?: boolean;
  workspace_id?: string | null;
  resolved_workspace_id?: string | null;
  project_id?: string | null;
  project?: ProjectSummary | null;
  config?: {
    pinned_panels?: PinnedPanel[];
    pinned_widgets?: PinnedWidget[];
    /** Pipeline-mode override. Controls whether the channel shows the
     *  pipeline launchpad + Findings panel chrome. "auto" (default):
     *  visible when \u22651 subscription exists. "on": always visible.
     *  "off": hidden even when subscriptions exist. */
    pipeline_mode?: "auto" | "on" | "off";
    /** Chat-screen layout mode. Controls which dashboard zones the chat
     *  screen renders. "full" (default): every zone. "rail-header-chat":
     *  rail + header chips, dock hidden. "rail-chat": rail only. Others
     *  hidden. "dashboard-only": chat screen replaced with a redirect
     *  card pointing at the channel dashboard. */
    layout_mode?: "full" | "rail-header-chat" | "rail-chat" | "dashboard-only";
    /** Chat presentation mode for the main channel surface. */
    chat_mode?: "default" | "terminal";
    /** Top-center header strip shell treatment for header-zone widgets. */
    header_backdrop_mode?: "default" | "glass" | "clear";
    /** Composer plan-control visibility. "auto" is the absent/default state. */
    plan_mode_control?: "auto" | "show" | "hide";
    /** Whether pinned channel widgets may export summaries into chat context. */
    pinned_widget_context_enabled?: boolean;
    /** Channel-scoped HTML widget SDK theme override. */
    widget_theme_ref?: string | null;
    /** Bot agency policy for channel dashboard widgets. */
    widget_agency_mode?: "propose" | "propose_and_fix";
    /** Workspace-relative project directory used as the channel file root and harness CWD. */
    project_path?: string | null;
    project_workspace_id?: string | null;
    harness_auto_compaction_enabled?: boolean;
    harness_auto_compaction_soft_remaining_pct?: number;
    harness_auto_compaction_hard_remaining_pct?: number;
    harness_auto_compaction?: {
      enabled?: boolean;
      soft_remaining_pct?: number;
      hard_remaining_pct?: number;
      last_prompted_at?: string | null;
      last_hard_compact_at?: string | null;
    };
    /** Per-channel reasoning/effort override, set by the `/effort` slash
     *  command. Resolved at run_stream entry into a ContextVar that the
     *  agent loop merges into `bot.model_params`. */
    effort_override?: "off" | "low" | "medium" | "high";
  };
  category?: string | null;
  tags?: string[];
  last_message_at?: string | null;
  /** Count of messages in the channel in the last 24h. Server-computed
   *  alongside `last_message_at`. Used by the spatial canvas channel tile
   *  for the "X today" recent-activity badge. */
  recent_message_count_24h?: number;
  /** First ~80 chars of the most recent message body, with newlines
   *  collapsed and ellipsis applied if truncated. Server-computed.
   *  Used by the spatial canvas channel tile snapshot view for
   *  progressive disclosure. */
  last_message_preview?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PinnedPanel {
  path: string;
  position: "right" | "bottom";
  pinned_at: string;
  pinned_by: string;
}

/** A tool result widget pinned to the side panel for persistent access. */
export interface PinnedWidget {
  id: string;
  tool_name: string;
  display_name: string;
  bot_id: string;
  widget_instance_id?: string | null;
  envelope: ToolResultEnvelope;
  position: number;
  pinned_at: string;
  widget_presentation?: WidgetPresentation | null;
  widget_contract?: WidgetContract | null;
  /** Legacy pinned-widget config shape. New widget work should use
   *  `widget_config` on dashboard pins and `{{widget_config.*}}` in templates;
   *  `{{config.*}}` remains as a compatibility alias. */
  config?: Record<string, unknown>;
  widget_health?: WidgetHealthSummary | null;
}

/** Scanner result for a standalone HTML widget discovered in a channel's
 *  workspace. Surfaced in the Add-widget sheet's "HTML widgets" tab and the
 *  dev panel Library. See `app/services/html_widget_scanner.py`. */
export interface HtmlWidgetEntry {
  /** Channel-workspace-relative path, e.g. `data/widgets/project-status/index.html`. */
  path: string;
  /** Display slug derived from the path (parent dir name for `index.html`, else file stem). */
  slug: string;
  /** Frontmatter `name` or slug fallback. */
  name: string;
  description: string;
  /** Frontmatter `display_label` or `name`. */
  display_label: string;
  /** Semver string; defaults to `"0.0.0"` when missing. */
  version: string;
  author: string | null;
  tags: string[];
  /** Lucide-react icon name, or null for the default. */
  icon: string | null;
  /** True when the file lives under a directory named `widgets/`. */
  is_bundle: boolean;
  /** True when the file was matched only by the `window.spindrel.*` grep
   *  rule — lives outside a `widgets/` folder. UI shows a "loose" badge. */
  is_loose: boolean;
  /** True when a sibling `widget.yaml` was found and parsed successfully. */
  has_manifest: boolean;
  size: number;
  modified_at: number;
  /** Provenance: which root was scanned to find this widget. Drives the
   *  catalog pill + the renderer's content-fetch endpoint dispatch. */
  source: "builtin" | "integration" | "channel";
  /** Set only for ``source === "integration"`` — the integration directory
   *  name (``frigate``, ``bennie``, …). */
  integration_id: string | null;
  /** Optional CSP allowances declared by the sibling ``widget.yaml``
   *  (``extra_csp: {directive: [https://origin, ...]}``). Forwarded onto
   *  the pin envelope so re-pinning across dashboards keeps cross-origin
   *  loads (Google Maps, Mapbox, …) working without re-emitting the widget. */
  extra_csp: Record<string, string[]> | null;
}

/** One entry per integration that ships standalone HTML widgets. */
export interface IntegrationHtmlWidgets {
  integration_id: string;
  entries: HtmlWidgetEntry[];
}

/** One entry per channel whose workspace holds standalone HTML widgets. */
export interface ChannelHtmlWidgets {
  channel_id: string;
  channel_name: string;
  entries: HtmlWidgetEntry[];
}

/** Response shape of ``GET /api/v1/widgets/html-widget-catalog``. */
export interface HtmlWidgetCatalog {
  builtin: HtmlWidgetEntry[];
  integrations: IntegrationHtmlWidgets[];
  channels: ChannelHtmlWidgets[];
}

export interface WidgetContract {
  definition_kind: "tool_widget" | "html_widget" | "native_widget";
  binding_kind: "tool_bound" | "standalone";
  instantiation_kind:
    | "direct_tool_call"
    | "preset"
    | "library_pin"
    | "runtime_emit"
    | "native_catalog";
  auth_model: "viewer" | "source_bot" | "server_context" | "host_native";
  state_model: "tool_result" | "bundle_runtime" | "instance_state";
  refresh_model: "none" | "state_poll" | "widget_runtime" | "instance_actions";
  theme_model?: string | null;
  supported_scopes?: string[];
  layout_hints?: WidgetLayoutHints | null;
  actions?: Array<{
    id: string;
    description?: string;
    args_schema?: Record<string, unknown>;
    returns_schema?: Record<string, unknown> | null;
  }>;
}

export interface WidgetPresentation {
  presentation_family: "card" | "chip" | "panel";
  panel_title?: string | null;
  show_panel_title?: boolean | null;
  layout_hints?: WidgetLayoutHints | null;
}

export interface WidgetOrigin {
  definition_kind: "tool_widget" | "html_widget" | "native_widget";
  instantiation_kind:
    | "direct_tool_call"
    | "preset"
    | "library_pin"
    | "runtime_emit"
    | "native_catalog";
  tool_name?: string;
  template_id?: string | null;
  preset_id?: string | null;
  tool_family?: string | null;
  widget_ref?: string | null;
  source_library_ref?: string | null;
  source_path?: string | null;
  source_kind?: ToolResultEnvelope["source_kind"];
  source_channel_id?: string | null;
  source_integration_id?: string | null;
  source_bot_id?: string | null;
}

export interface WidgetLayoutHints {
  preferred_zone?: "chip" | "rail" | "header" | "dock" | "grid" | string | null;
  min_cells?: { w?: number; h?: number } | null;
  max_cells?: { w?: number; h?: number } | null;
}

export interface WidgetConfigSchemaField {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
}

export interface WidgetConfigSchema {
  type?: string;
  required?: string[];
  properties?: Record<string, WidgetConfigSchemaField>;
}

/** One entry in the unified pinnable-widget catalog. Covers five scopes —
 *  the three ``widget://`` namespaces (``core`` / ``bot`` / ``workspace``)
 *  AND scanner-sourced ``integration`` / ``channel`` HTML widgets. The old
 *  "HTML widgets" tab was folded into Library so a user can pin any flavor
 *  from one surface.
 *
 *  Pairs with ``GET /api/v1/widgets/library-widgets``. */
export interface WidgetLibraryEntry {
  /** Folder name under the scope root (widget:// scopes) or frontmatter
   *  name / slug for scanner-sourced scopes — also the machine identifier
   *  used when composing ``widget://<scope>/<name>/...`` refs. */
  name: string;
  /** Which on-disk root this came from. */
  scope: "core" | "bot" | "workspace" | "integration" | "channel";
  /** Bundle format. ``html`` = iframe widget, ``suite`` = multi-widget
   *  bundle sharing a SQLite DB. Tool-renderer ``template`` entries are
   *  filtered out server-side — they can't be pinned without runtime args. */
  format: "html" | "suite" | "native_app";
  widget_kind?: "html" | "template" | "native_app";
  widget_binding?: "standalone" | "tool_bound";
  theme_support?: "html" | "template" | "none";
  group_kind?: "suite" | "package" | null;
  group_ref?: string | null;
  widget_ref?: string | null;
  supported_scopes?: string[];
  config_schema?: WidgetConfigSchema | null;
  widget_contract?: WidgetContract | null;
  widget_presentation?: WidgetPresentation | null;
  layout_hints?: WidgetLayoutHints | null;
  actions?: Array<{
    id: string;
    description?: string;
    args_schema?: Record<string, unknown>;
    returns_schema?: Record<string, unknown> | null;
  }>;
  display_label?: string;
  panel_title?: string | null;
  show_panel_title?: boolean | null;
  description?: string;
  version?: string;
  tags?: string[];
  icon?: string | null;
  updated_at?: number;
  /** Scanner scopes (integration / channel) carry a relative path to the
   *  bundle's ``index.html`` so the pin envelope can route its content
   *  fetch to the matching ``/html-widget-content/*`` endpoint. */
  path?: string;
  /** Scanner-derived slug (parent dir or file stem). */
  slug?: string;
  /** Present on integration-scoped entries. */
  integration_id?: string | null;
  /** Present on channel-scoped entries. */
  channel_id?: string | null;
  /** Scanner flag — HTML file is outside a ``widgets/`` dir but references
   *  ``window.spindrel.``. */
  is_loose?: boolean;
  /** True when a sibling ``widget.yaml`` was found next to the html file. */
  has_manifest?: boolean;
  /** Populated on ``bot`` scope entries from the ``/library-widgets/all-bots``
   *  endpoint so the dev-panel library can group/badge rows by bot. */
  bot_id?: string | null;
  bot_name?: string | null;
}

/** Response shape of ``GET /api/v1/widgets/library-widgets``. */
export interface WidgetLibraryCatalog {
  core: WidgetLibraryEntry[];
  integration: WidgetLibraryEntry[];
  bot: WidgetLibraryEntry[];
  workspace: WidgetLibraryEntry[];
  channel: WidgetLibraryEntry[];
}

/** A widget pinned to the chat-less `/widgets` dashboard. Row shape mirrors
 *  `channel.config.pinned_widgets[]` so the same renderer handles both. */
export interface WidgetDashboardPin {
  id: string;
  dashboard_key: string;
  position: number;
  source_kind: "channel" | "adhoc";
  source_channel_id: string | null;
  widget_instance_id?: string | null;
  source_bot_id: string | null;
  tool_name: string;
  tool_args: Record<string, unknown>;
  widget_config: Record<string, unknown>;
  widget_origin?: WidgetOrigin | null;
  provenance_confidence?: "authoritative" | "inferred" | string | null;
  widget_presentation?: WidgetPresentation | null;
  envelope: ToolResultEnvelope;
  display_label: string | null;
  grid_layout: GridLayoutItem | Record<string, never>;
  /**
   * When true, this pin claims the dashboard's main area in `panel` layout
   * mode and the grid renders only rail-zone pins alongside it. At most one
   * pin per dashboard may be the main panel (enforced by a partial unique
   * index on the server).
   */
  is_main_panel: boolean;
  /** Chat-surface zone the pin lives on. Authored directly by dragging the
   *  tile between the four canvases on a channel dashboard. User dashboards
   *  always carry ``"grid"``. */
  zone: ChatZone;
  config_schema?: WidgetConfigSchema | null;
  widget_contract?: WidgetContract | null;
  available_actions?: Array<{
    id: string;
    description?: string;
    args_schema?: Record<string, unknown>;
    returns_schema?: Record<string, unknown> | null;
  }>;
  widget_health?: WidgetHealthSummary | null;
  pinned_at: string | null;
  updated_at: string | null;
}

export type WidgetHealthStatus = "healthy" | "warning" | "failing" | "unknown";

export interface WidgetHealthIssue {
  phase: string;
  severity: "error" | "warning" | "info" | string;
  message: string;
  kind?: string;
  evidence?: Record<string, unknown>;
}

export interface WidgetHealthPhase {
  name: string;
  status: WidgetHealthStatus | string;
  message: string;
  duration_ms?: number;
}

export interface WidgetHealthSummary {
  check_id: string;
  pin_id: string | null;
  target_kind: string;
  target_ref: string;
  status: WidgetHealthStatus;
  summary: string;
  phases: WidgetHealthPhase[];
  issues: WidgetHealthIssue[];
  event_counts: Record<string, number>;
  checked_at: string;
}

export type WidgetUsefulnessStatus = "healthy" | "has_suggestions" | "needs_attention" | "action_required" | string;
export type WidgetUsefulnessSeverity = "info" | "low" | "medium" | "high" | string;
export type WidgetUsefulnessSurface = "dashboard" | "chat" | "project" | string;

export interface WidgetUsefulnessRecommendation {
  proposal_id?: string;
  type: string;
  severity: WidgetUsefulnessSeverity;
  surface: WidgetUsefulnessSurface;
  pin_id: string | null;
  label: string | null;
  reason: string;
  evidence: Record<string, unknown>;
  suggested_next_action: string;
  requires_policy_decision: boolean;
  apply?: {
    id: string;
    action: string;
    label: string;
    description: string;
    impact?: string;
    [key: string]: unknown;
  };
}

export interface WidgetUsefulnessAssessment {
  channel_id: string;
  channel_name: string | null;
  dashboard_key: string;
  status: WidgetUsefulnessStatus;
  summary: string;
  pin_count: number;
  chat_visible_pin_count: number;
  layout_mode: string;
  widget_agency_mode: "propose" | "propose_and_fix" | string;
  project_scope_available: boolean;
  project: Record<string, unknown> | null;
  context_export: Record<string, unknown>;
  recommendations: WidgetUsefulnessRecommendation[];
  findings?: WidgetUsefulnessRecommendation[];
}

export interface WidgetAgencyReceipt {
  id: string;
  kind?: "agency" | "authoring" | string;
  channel_id?: string | null;
  dashboard_key: string;
  action: string;
  summary: string;
  reason?: string | null;
  bot_id?: string | null;
  session_id?: string | null;
  correlation_id?: string | null;
  task_id?: string | null;
  affected_pin_ids: string[];
  before_state: Record<string, unknown>;
  after_state: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at?: string | null;
}

export interface WidgetAgencyReceiptList {
  receipts: WidgetAgencyReceipt[];
}

/** {x, y, w, h} in the 12-column dashboard grid. Empty object when unset. */
export interface GridLayoutItem {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Discriminator telling `PinnedToolWidget` which surface it lives on.
 *  ``compact`` is only meaningful for channel-scope pins:
 *    - ``"chip"`` — minimal 180×32 rendering used by `ChannelHeaderChip`.
 *
 *  ``kind: "dashboard"`` carries an optional ``channelId`` — set when the
 *  dashboard is a channel dashboard (slug ``channel:<uuid>``), omitted for
 *  user/global dashboards. This is the canonical source for ``window.spindrel.channelId``
 *  inside pinned HTML widgets; do not re-derive it from envelope fields. */
export type WidgetScope =
  | { kind: "channel"; channelId: string; compact?: false | "chip" }
  | { kind: "dashboard"; channelId?: string };

/** Chat-side zone a dashboard pin belongs to. Stored directly on the pin
 *  (``widget_dashboard_pins.zone``) and authored via the multi-canvas
 *  channel dashboard. ``"grid"`` means dashboard-only — the pin does not
 *  surface on the chat screen. */
export type ChatZone = "rail" | "header" | "dock" | "grid";

// Full channel settings (matches server ChannelSettingsOut)
export interface ChannelSettings {
  id: string;
  name: string;
  bot_id: string;
  client_id?: string;
  integration?: string;
  active_session_id?: string;
  require_mention: boolean;
  passive_memory: boolean;
  private: boolean;
  protected?: boolean;
  user_id?: string | null;
  allow_bot_messages: boolean;
  workspace_rag: boolean;
  pinned_widget_context_enabled: boolean;
  thinking_display?: string;
  tool_output_display?: string;
  max_iterations?: number;
  task_max_run_seconds?: number | null;
  channel_prompt?: string;
  channel_prompt_workspace_file_path?: string | null;
  channel_prompt_workspace_id?: string | null;
  context_compaction: boolean;
  compaction_interval?: number;
  compaction_keep_turns?: number;
  memory_knowledge_compaction_prompt?: string;
  compaction_prompt_template_id?: string | null;
  compaction_workspace_file_path?: string | null;
  compaction_workspace_id?: string | null;
  history_mode?: string | null;
  compaction_model?: string;
  compaction_model_provider_id?: string | null;
  trigger_heartbeat_before_compaction?: boolean | null;
  harness_auto_compaction_enabled?: boolean;
  harness_auto_compaction_soft_remaining_pct?: number;
  harness_auto_compaction_hard_remaining_pct?: number;
  // Memory flush (dedicated pre-compaction memory save)
  memory_flush_enabled?: boolean | null;
  memory_flush_model?: string | null;
  memory_flush_model_provider_id?: string | null;
  memory_flush_prompt?: string | null;
  memory_flush_prompt_template_id?: string | null;
  memory_flush_workspace_file_path?: string | null;
  memory_flush_workspace_id?: string | null;
  section_index_count?: number | null;
  section_index_verbosity?: string | null;
  model_override?: string | null;
  model_provider_id_override?: string | null;
  fallback_models?: Array<{ model: string; provider_id?: string | null }>;
  // Tool / skill restrictions
  local_tools_disabled?: string[] | null;
  mcp_servers_disabled?: string[] | null;
  client_tools_disabled?: string[] | null;
  // Workspace overrides
  workspace_base_prompt_enabled?: boolean | null;
  workspace_schema_template_id?: string | null;
  workspace_schema_content?: string | null;
  index_segments?: Array<{ path_prefix: string; patterns?: string[]; embedding_model?: string | null; similarity_threshold?: number; top_k?: number }>;
  index_segment_defaults?: {
    embedding_model: string;
    patterns: string[];
    similarity_threshold: number;
    top_k: number;
  } | null;
  workspace_id?: string | null;
  resolved_workspace_id?: string | null;
  project_id?: string | null;
  project?: ProjectSummary | null;
  project_workspace_id?: string | null;
  project_path?: string | null;
  resolved_project_workspace_id?: string | null;
  category?: string | null;
  tags?: string[];
  /** Pipeline-mode override on this channel. "auto" (default) shows the
   *  pipeline launchpad when subscriptions exist; "on" forces it visible;
   *  "off" hides it even with subscriptions. Stored in `channel.config`. */
  pipeline_mode?: "auto" | "on" | "off";
  /** Chat-screen layout mode. Controls which dashboard zones render on the
   *  chat screen. See `Channel.config.layout_mode` for the authoritative
   *  shape. "full" (default), "rail-header-chat", "rail-chat",
   *  "dashboard-only". Stored in `channel.config`. */
  layout_mode?: "full" | "rail-header-chat" | "rail-chat" | "dashboard-only";
  /** Chat presentation mode for the main channel screen. Stored in
   *  `channel.config`. "default" keeps the current UI; "terminal" swaps in
   *  the command-first transcript treatment. */
  chat_mode?: "default" | "terminal";
  /** Top-center chat header strip shell treatment. Stored in `channel.config`. */
  header_backdrop_mode?: "default" | "glass" | "clear";
  /** Composer plan-control visibility. "auto" hides dormant control on non-harness channels and shows it for harness channels. Stored in `channel.config`. */
  plan_mode_control?: "auto" | "show" | "hide";
  /** Channel-scoped HTML widget SDK theme override. Null/absent inherits the global default. */
  widget_theme_ref?: string | null;
  /** Bot agency policy for channel dashboard widgets. */
  widget_agency_mode?: "propose" | "propose_and_fix";
}

export interface WidgetTheme {
  ref: string;
  name: string;
  slug: string;
  is_builtin: boolean;
  forked_from_ref?: string | null;
  light_tokens: Record<string, string>;
  dark_tokens: Record<string, string>;
  custom_css: string;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface WidgetThemeDefaultResponse {
  ref: string;
  builtin_ref: string;
}

export interface ResolvedWidgetThemeResponse {
  theme_ref: string;
  explicit_channel_theme_ref?: string | null;
  global_theme_ref: string;
  builtin_theme_ref: string;
  theme: WidgetTheme;
}

export interface EffectiveTools {
  local_tools: string[];
  mcp_servers: string[];
  client_tools: string[];
  pinned_tools: string[];
  skills: { id: string; mode: string; name?: string }[];
  mode: Record<string, "inherit" | "disabled">;
  disabled: Record<string, string[]>;
}

// Model types
export interface LlmModel {
  id: string;
  display: string;
  max_tokens?: number;
  download_status?: "cached" | "not_downloaded" | "downloading";
  size_mb?: number;
  supports_reasoning?: boolean;
  supports_image_generation?: boolean;
}

export interface ModelGroup {
  provider_id?: string;
  provider_name: string;
  provider_type: string;
  models: LlmModel[];
}

// Completions for @-tag autocomplete
export interface CompletionItem {
  value: string;
  label: string;
  description?: string;
}

export type SlashCommandId = string;
export type SlashCommandSurface = "channel" | "session";
export type EffortLevel = "off" | "low" | "medium" | "high";
export type ChatModeId = "default" | "terminal";
export type ThemeId = "light" | "dark";

export type SlashCommandArgSource = "free_text" | "enum" | "model";

export interface SlashCommandArgSpec {
  name: string;
  source: SlashCommandArgSource;
  required: boolean;
  enum: string[] | null;
}

export interface SlashCommandSpec {
  id: SlashCommandId;
  label: string;
  description: string;
  surfaces: SlashCommandSurface[];
  local_only: boolean;
  args: SlashCommandArgSpec[];
  runtime_native?: boolean;
  runtime_command_id?: string;
  runtime_command_readonly?: boolean;
  runtime_command_mutability?: "readonly" | "mutating" | "argument_sensitive" | string;
  runtime_command_interaction_kind?: string;
  runtime_command_fallback_behavior?: string;
}

export interface SlashCommandCatalog {
  commands: SlashCommandSpec[];
}

export interface SlashCommandResult {
  command_id: string;
  result_type: string;
  payload: Record<string, any>;
  fallback_text: string;
}

export interface SlashCommandSideEffectPayload {
  effect: "stop" | "compact" | "plan" | "effort" | "model" | "rename" | "style";
  scope_kind: "channel" | "session";
  scope_id: string;
  title: string;
  detail: string;
  status?: "queued" | "started";
  message_id?: string;
}

export interface SlashCommandFindMatch {
  message_id: string;
  session_id: string;
  role: string;
  preview: string;
  created_at?: string | null;
}

export interface SlashCommandFindResultsPayload {
  scope_kind: "channel" | "session";
  scope_id: string;
  query: string;
  matches: SlashCommandFindMatch[];
  truncated: boolean;
}

export interface ContextSummaryPayload {
  scope_kind: "channel" | "session";
  scope_id: string;
  session_id?: string | null;
  bot_id: string;
  title: string;
  headline: string;
  budget?: {
    utilization?: number | null;
    consumed_tokens?: number | null;
    total_tokens?: number | null;
    gross_prompt_tokens?: number | null;
    current_prompt_tokens?: number | null;
    cached_prompt_tokens?: number | null;
    completion_tokens?: number | null;
    context_profile?: string | null;
    context_origin?: string | null;
    live_history_turns?: number | null;
    source?: string | null;
  } | null;
  top_categories: Array<{
    key: string;
    label: string;
    tokens_approx: number;
    percentage: number;
    description: string;
  }>;
  message_count?: number | null;
  total_chars?: number | null;
  notes: string[];
  pinned_widget_context?: {
    enabled: boolean;
    total_pins: number;
    exported_count: number;
    skipped_count: number;
    total_chars: number;
    truncated?: boolean;
    block_text?: string | null;
    rows: Array<{
      pin_id: string;
      label: string;
      summary: string;
      hint?: string | null;
      line: string;
      chars: number;
    }>;
    skipped: Array<{
      pin_id: string;
      label: string;
      reason: string;
    }>;
  } | null;
}

// Session types
export interface Session {
  id: string;
  bot_id: string;
  client_id?: string;
  channel_id?: string;
  parent_session_id?: string;
  root_session_id?: string;
  depth: number;
  created_at: string;
  updated_at: string;
  summary?: string;
}

// Attachment types
export interface AttachmentBrief {
  id: string;
  type: string; // image, file, text, audio, video
  filename: string;
  mime_type: string;
  size_bytes: number;
  description?: string;
  has_file_data: boolean;
}

// Message types
export type AssistantTurnBodyEntry =
  | {
      id: string;
      kind: "text";
      text: string;
    }
  | {
      id: string;
      kind: "tool_call";
      toolCallId: string;
    };

export interface AssistantTurnBody {
  version: 1;
  items: AssistantTurnBodyEntry[];
}

export interface Message {
  id: string;
  session_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  correlation_id?: string;
  tool_calls?: ToolCall[];
  attachments?: AttachmentBrief[];
  metadata?: Record<string, any>;
  created_at: string;
}

export type ToolSurface = "transcript" | "widget" | "rich_result";

export interface ToolCallSummary {
  kind: "lookup" | "read" | "write" | "diff" | "action" | "result" | "error";
  subject_type: "file" | "skill" | "widget" | "tool" | "session" | "channel" | "entity" | "generic";
  label: string;
  target_id?: string | null;
  target_label?: string | null;
  path?: string | null;
  preview_text?: string | null;
  diff_stats?: { additions: number; deletions: number } | null;
  error?: string | null;
}

/** OpenAI function-call format as stored in DB */
export interface ToolCall {
  id: string;
  type?: string;
  function?: { name: string; arguments: string };
  // Flattened form (for convenience)
  name?: string;
  arguments?: string;
  args?: string;
  tool_name?: string;
  /** Approval-side discriminator for harness vs local/client/mcp. Only set for
   *  rows that carry an approval (the SSE `approval_request` event populates
   *  it; persisted ToolCall rows don't carry it). */
  tool_type?: string;
  surface?: ToolSurface;
  summary?: ToolCallSummary | null;
}

/** Extract name and arguments from a ToolCall regardless of format */
export function normalizeToolCall(tc: ToolCall): { name: string; arguments: string } {
  if (tc.function) {
    return { name: tc.function.name, arguments: tc.function.arguments };
  }
  return { name: tc.name ?? tc.tool_name ?? "unknown", arguments: tc.arguments ?? tc.args ?? "{}" };
}

/**
 * Rendered tool result envelope — mirrors `ToolResultEnvelope.compact_dict()`
 * from `app/agent/tool_dispatch.py`. Carries the user-visible body for the
 * web UI's mimetype-keyed renderer (markdown / json-tree / sandboxed-html /
 * unified-diff / file-listing). The full untruncated body lives on the
 * persisted `tool_calls` row when `truncated=true`; the UI lazy-fetches it
 * via `GET /api/v1/sessions/{sid}/tool-calls/{record_id}/result`.
 */
export interface ToolResultEnvelope {
  tool_call_id?: string | null;
  content_type: string;
  body: string | Record<string, unknown> | null;
  /** Stable view identity used by mode-aware render registries. */
  view_key?: string | null;
  /** Structured result data shared by default, terminal, and future render modes. */
  data?: unknown;
  /** Optional source template identity for template-backed views. */
  template_id?: string | null;
  plain_body: string;
  display: "badge" | "inline" | "panel";
  truncated: boolean;
  record_id: string | null;
  byte_size: number;
  widget_type?: string;
  /** Resolved display label from widget template (e.g., entity name) */
  display_label?: string | null;
  panel_title?: string | null;
  show_panel_title?: boolean | null;
  /** When true, this widget supports state refresh on load via state_poll */
  refreshable?: boolean;
  /** If set, pinned widgets should auto-refresh on this interval (seconds) */
  refresh_interval_seconds?: number | null;
  /** For file-backed widgets (emit_html_widget path-mode): source-relative path
   *  the renderer fetches content from. Paired with `source_channel_id` for
   *  channel-sourced widgets, or with `source_integration_id` for integration-
   *  sourced widgets. Built-in widgets resolve ``source_path`` against
   *  ``app/tools/local/widgets/`` server-side. */
  source_path?: string | null;
  /** Provenance of a path-backed widget. When omitted, the envelope behaves
   *  as if ``"channel"`` — back-compat default for existing pins. */
  source_kind?: "channel" | "builtin" | "integration" | "library" | null;
  /** Channel id scoping `source_path` to its channel workspace. Required
   *  for ``source_kind === "channel"`` envelopes. */
  source_channel_id?: string | null;
  /** Integration id scoping `source_path` to ``integrations/<id>/widgets/``.
   *  Set only for ``source_kind === "integration"`` envelopes. */
  source_integration_id?: string | null;
  /** Library ref scoping the envelope to a ``widget://<scope>/<name>/`` bundle.
   *  Set only for ``source_kind === "library"`` envelopes. The renderer fetches
   *  fresh body from ``/api/v1/widgets/html-widget-content/library?ref=...``. */
  source_library_ref?: string | null;
  /** Bot that emitted the envelope. Drives the widget-auth mint so
   *  interactive HTML widgets authenticate as this bot, not as the
   *  viewing user. */
  source_bot_id?: string | null;
  /** Per-widget CSP extensions — third-party origins the iframe is
   *  permitted to load for this envelope. Keys are snake_case CSP
   *  directives (`script_src`, `connect_src`, `img_src`, `style_src`,
   *  `font_src`, `media_src`, `frame_src`, `worker_src`), values are
   *  arrays of `https://host[:port]` origins. Backend-validated at emit
   *  time; the renderer merges them into the iframe's Content-Security-
   *  Policy (appending to baseline `'self'` + inline allowances). */
  extra_csp?: Record<string, string[]> | null;
  /** Hint to the dashboard pinning UI: when "panel", pre-checks the
   *  Promote-to-panel option in EditPinDrawer so the widget claims the
   *  dashboard's main area instead of a normal grid tile. Only meaningful
   *  for `application/vnd.spindrel.html+interactive` envelopes. */
  display_mode?: "inline" | "panel" | null;
  /** Runtime flavor for the body. Default `html` renders the body as plain
   *  HTML inside the iframe. `react` adds vendored React + ReactDOM +
   *  Babel-standalone and auto-compiles `<script type="text/babel"
   *  data-spindrel-react>` blocks. Both flavors share the same theme,
   *  sandbox, and `window.spindrel.api` auth — `react` is the ergonomic
   *  flavor for stateful bot/user-authored widgets. Library / path-mode
   *  widgets can also self-declare via `runtime: react` in YAML
   *  frontmatter; envelope value wins. */
  runtime?: "html" | "react" | null;
}

/** Action definition for interactive widget components (toggle, button, select, etc.) */
export interface WidgetAction {
  /** "tool" dispatches through tool_dispatch, "api" calls a REST endpoint directly,
   *  "widget_config" patches the pinned widget's config and returns a refreshed envelope. */
  dispatch: "tool" | "api" | "widget_config" | "native_widget";
  /** For dispatch:"tool" — the tool name to call */
  tool?: string;
  /** For dispatch:"api" — the endpoint path (allowlisted internal paths only) */
  endpoint?: string;
  method?: "POST" | "PUT" | "PATCH" | "DELETE";
  /** Static args merged with the dynamic value from the interactive element */
  args?: Record<string, unknown>;
  /** For dispatch:"widget_config" — the config patch to shallow-merge into the pin. */
  config?: Record<string, unknown>;
  /** For dispatch:"native_widget" — the action id exposed by a native widget. */
  action?: string;
  /** Key name for the dynamic value (e.g., toggle sends {[value_key]: true/false}) */
  value_key?: string;
  /** Flip the value client-side before server confirms */
  optimistic?: boolean;
}

// Chat types
export interface ChatAttachment {
  type: string;
  content: string; // base64
  mime_type: string;
  name?: string;
}

export interface ChatFileMetadata {
  filename: string;
  mime_type: string;
  size_bytes: number;
  file_data: string; // base64
}

export interface ChatRequest {
  message: string;
  bot_id: string;
  client_id: string;
  session_id?: string;
  channel_id?: string;
  external_delivery?: "channel" | "none";
  msg_metadata?: Record<string, unknown>;
  model_override?: string;
  model_provider_id_override?: string | null;
  attachments?: ChatAttachment[];
  file_metadata?: ChatFileMetadata[];
  audio_data?: string;
  audio_format?: string;
  audio_native?: boolean;
}

export interface ChatResponse {
  response: string;
  session_id: string;
  client_actions?: ClientAction[];
}

export interface ClientAction {
  action: string;
  params?: Record<string, unknown>;
}

// SSE event types
export type SSEEventType =
  | "skill_context"
  | "memory_context"
  | "tool_start"
  | "tool_request"
  | "tool_result"
  | "assistant_text"
  | "text_delta"
  | "thinking"
  | "thinking_content"
  | "transcript"
  | "response"
  | "compaction_start"
  | "compaction_done"
  | "warning"
  | "error"
  | "queued"
  | "cancelled"
  | "passive_stored"
  | "secret_warning"
  | "approval_request"
  | "approval_resolved"
  | "delegation_post"
  | "pending_tasks"
  | "stream_meta"
  | "pending_member_stream"
  | "context_budget"
  | "skill_auto_inject"
  | "llm_status";

export interface SSEEvent {
  event: SSEEventType;
  data: unknown;
}

// Auth types
export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  integration_config: Record<string, any>;
  is_admin: boolean;
  auth_method: string;
  scopes: string[];
}

export interface AuthStatus {
  setup_required: boolean;
  google_enabled: boolean;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  user: AuthUser;
}

// Shared Workspace types
export interface WorkspaceBot {
  bot_id: string;
  bot_name: string;
  role: string;
  cwd_override?: string | null;
  write_access?: string[];
  user_id?: string | null;
}

export interface SharedWorkspace {
  id: string;
  name: string;
  description?: string | null;
  env: Record<string, string>;
  workspace_base_prompt_enabled: boolean;
  indexing_config?: Record<string, any> | null;
  write_protected_paths?: string[];
  status: string;
  created_by_user_id?: string | null;
  created_at: string;
  updated_at: string;
  bots: WorkspaceBot[];
}

export interface ProjectSummary {
  id: string;
  workspace_id: string;
  applied_blueprint_id?: string | null;
  name: string;
  slug: string;
  root_path: string;
}

export interface ProjectBlueprintSummary {
  id: string;
  workspace_id?: string | null;
  name: string;
  slug: string;
  description?: string | null;
}

export interface ProjectBlueprint extends ProjectBlueprintSummary {
  default_root_path_pattern?: string | null;
  prompt?: string | null;
  prompt_file_path?: string | null;
  folders?: string[];
  files?: Record<string, string>;
  knowledge_files?: Record<string, string>;
  repos?: Array<Record<string, any>>;
  setup_commands?: Array<Record<string, any>>;
  env?: Record<string, string>;
  required_secrets?: string[];
  metadata_?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface ProjectSecretBinding {
  id: string;
  logical_name: string;
  secret_value_id?: string | null;
  secret_value_name?: string | null;
  bound: boolean;
}

export interface Project extends ProjectSummary {
  description?: string | null;
  prompt?: string | null;
  prompt_file_path?: string | null;
  metadata_?: Record<string, any>;
  resolved?: {
    project_id?: string | null;
    name?: string | null;
    workspace_id: string;
    path: string;
    host_path: string;
  } | null;
  blueprint?: ProjectBlueprintSummary | null;
  secret_bindings?: ProjectSecretBinding[];
  attached_channel_count?: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectInstance {
  id: string;
  workspace_id: string;
  project_id: string;
  root_path: string;
  status: "preparing" | "ready" | "failed" | "expired" | "deleted" | string;
  source: string;
  source_snapshot?: Record<string, any>;
  setup_result?: Record<string, any>;
  metadata_?: Record<string, any>;
  owner_kind?: "manual" | "task" | "session" | null;
  owner_id?: string | null;
  expires_at?: string | null;
  deleted_at?: string | null;
  created_at: string;
  updated_at: string;
  resolved?: {
    project_id?: string | null;
    project_instance_id?: string | null;
    name?: string | null;
    workspace_id: string;
    path: string;
    host_path: string;
  } | null;
}

export interface ProjectRunReceipt {
  id: string;
  project_id: string;
  project_instance_id?: string | null;
  task_id?: string | null;
  session_id?: string | null;
  bot_id?: string | null;
  idempotency_key?: string | null;
  status: "reported" | "completed" | "blocked" | "failed" | "needs_review" | string;
  summary: string;
  handoff_type?: string | null;
  handoff_url?: string | null;
  branch?: string | null;
  base_branch?: string | null;
  commit_sha?: string | null;
  changed_files?: string[];
  tests?: Array<Record<string, any> | string>;
  screenshots?: Array<Record<string, any> | string>;
  metadata?: Record<string, any>;
  created_at: string;
}

export interface ProjectCodingRunTask {
  id: string;
  status: string;
  title?: string | null;
  bot_id: string;
  channel_id?: string | null;
  session_id?: string | null;
  project_instance_id?: string | null;
  correlation_id?: string | null;
  created_at?: string | null;
  scheduled_at?: string | null;
  run_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  machine_target_grant?: {
    provider_id: string;
    target_id: string;
    grant_id?: string | null;
    grant_source_task_id?: string | null;
    capabilities?: string[] | null;
    allow_agent_tools?: boolean | null;
    expires_at?: string | null;
    provider_label?: string | null;
    target_label?: string | null;
    diagnostics?: Array<{ severity: string; code: string; message: string }> | null;
  } | null;
}

export interface ProjectCodingRun {
  id: string;
  project_id: string;
  status: "pending" | "running" | "completed" | "blocked" | "failed" | "needs_review" | string;
  request?: string;
  branch?: string | null;
  base_branch?: string | null;
  repo?: Record<string, any>;
  runtime_target?: Record<string, any>;
  source_work_pack_id?: string | null;
  parent_task_id?: string | null;
  root_task_id?: string | null;
  continuation_index?: number;
  continuation_feedback?: string | null;
  continuation_count?: number;
  latest_continuation?: Record<string, any> | null;
  continuations?: Array<Record<string, any>>;
  task: ProjectCodingRunTask;
  receipt?: ProjectRunReceipt | null;
  activity?: Array<Record<string, any>>;
  review?: {
    status?: string;
    blocker?: string | null;
    reviewed?: boolean;
    reviewed_at?: string | null;
    reviewed_by?: string | null;
    review_task_id?: string | null;
    review_session_id?: string | null;
    review_summary?: string | null;
    review_details?: Record<string, any>;
    merge_method?: "squash" | "merge" | "rebase" | string | null;
    merged_at?: string | null;
    merge_commit_sha?: string | null;
    handoff_url?: string | null;
    pr?: {
      url?: string | null;
      state?: string | null;
      draft?: boolean | null;
      merge_state?: string | null;
      review_decision?: string | null;
      checks_status?: string | null;
    };
    steps?: Record<string, { status?: string; summary?: string | null }>;
    evidence?: {
      changed_files_count?: number;
      tests_count?: number;
      screenshots_count?: number;
      has_tests?: boolean;
      has_screenshots?: boolean;
    };
    instance?: {
      id?: string;
      status?: string;
      root_path?: string;
      owner_kind?: string | null;
      owner_id?: string | null;
      expires_at?: string | null;
      deleted_at?: string | null;
    } | null;
    actions?: {
      can_refresh?: boolean;
      can_mark_reviewed?: boolean;
      can_cleanup_instance?: boolean;
      can_request_changes?: boolean;
    };
  };
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ProjectCodingRunSchedule {
  id: string;
  project_id: string;
  channel_id?: string | null;
  title: string;
  request?: string;
  status: string;
  enabled: boolean;
  scheduled_at?: string | null;
  recurrence?: string | null;
  run_count: number;
  last_run?: {
    id?: string;
    task_id?: string;
    status?: string;
    created_at?: string | null;
    branch?: string | null;
  } | null;
  created_at?: string | null;
  machine_target_grant?: ProjectCodingRunTask["machine_target_grant"];
}

export interface SessionProjectInstance {
  session_id: string;
  project_instance_id?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  workspace_id?: string | null;
  status?: "shared" | "preparing" | "ready" | "failed" | "expired" | "deleted" | string | null;
  root_path?: string | null;
  expires_at?: string | null;
  created_at?: string | null;
}

export interface ProjectSetupRun {
  id: string;
  project_id: string;
  status: string;
  source: string;
  plan?: Record<string, any>;
  result?: Record<string, any>;
  logs?: string[];
  started_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectSetup {
  plan: {
    source: string;
    ready: boolean;
    reasons?: string[];
    repos?: Array<Record<string, any>>;
    commands?: Array<Record<string, any>>;
    env?: Record<string, string>;
    secret_slots?: Array<Record<string, any>>;
    missing_secrets?: string[];
  };
  runs: ProjectSetupRun[];
}

export interface ProjectRuntimeEnv {
  source: string;
  ready: boolean;
  env_default_keys?: string[];
  secret_keys?: string[];
  missing_secrets?: string[];
  invalid_env_keys?: string[];
  reserved_env_keys?: string[];
}

export interface ProjectWrite {
  workspace_id?: string | null;
  name?: string | null;
  slug?: string | null;
  description?: string | null;
  root_path?: string | null;
  prompt?: string | null;
  prompt_file_path?: string | null;
  metadata_?: Record<string, any> | null;
}

export interface ProjectBlueprintWrite {
  workspace_id?: string | null;
  name?: string | null;
  slug?: string | null;
  description?: string | null;
  default_root_path_pattern?: string | null;
  prompt?: string | null;
  prompt_file_path?: string | null;
  folders?: string[] | null;
  files?: Record<string, string> | null;
  knowledge_files?: Record<string, string> | null;
  repos?: Array<Record<string, any>> | null;
  setup_commands?: Array<Record<string, any>> | null;
  env?: Record<string, string> | null;
  required_secrets?: string[] | null;
  metadata_?: Record<string, any> | null;
}

export interface ProjectFromBlueprintWrite {
  blueprint_id: string;
  workspace_id?: string | null;
  name: string;
  slug?: string | null;
  description?: string | null;
  root_path?: string | null;
  secret_bindings?: Record<string, string | null>;
}

export interface WorkspaceCreate {
  name: string;
  description?: string;
  env?: Record<string, string>;
  workspace_base_prompt_enabled?: boolean;
  write_protected_paths?: string[];
  created_by_user_id?: string;
}

export interface WorkspaceUpdate {
  name?: string;
  description?: string;
  env?: Record<string, string>;
  workspace_base_prompt_enabled?: boolean;
  write_protected_paths?: string[];
  indexing_config?: Record<string, any>;
}

export interface WorkspaceFileEntry {
  name: string;
  is_dir: boolean;
  size?: number | null;
  path: string;
  modified_at?: number | null; // unix timestamp (seconds)
  display_name?: string | null; // from .channel_info for channel UUID dirs
}

// Context breakdown types
export interface ContextCategory {
  key: string;
  label: string;
  chars: number;
  tokens_approx: number;
  percentage: number;
  category: "static" | "rag" | "conversation" | "compaction";
  description: string;
}

export interface CompactionState {
  enabled: boolean;
  has_summary: boolean;
  summary_chars: number;
  messages_since_watermark: number;
  total_messages: number;
  compaction_interval: number;
  compaction_keep_turns: number;
  turns_until_next: number | null;
}

export interface RerankState {
  enabled: boolean;
  model: string;
  threshold_chars: number;
  max_chunks: number;
  total_rag_chars: number;
  would_rerank: boolean;
}

export interface EffectiveSetting {
  value: any;
  source: "channel" | "bot" | "global";
}

export interface CompressionState {
  enabled: boolean;
  model: string | null;
  threshold: number;
  keep_turns: number;
  conversation_chars: number;
  would_compress: boolean;
}

export interface ContextBreakdown {
  channel_id: string;
  session_id: string | null;
  bot_id: string;
  context_profile?: string | null;
  context_origin?: string | null;
  live_history_turns?: number | null;
  mandatory_static_injections?: string[];
  optional_static_injections?: string[];
  categories: ContextCategory[];
  total_chars: number;
  total_tokens_approx: number;
  compaction: CompactionState;
  compression?: CompressionState | null;
  reranking: RerankState;
  effective_settings: Record<string, EffectiveSetting>;
  context_budget?: {
    context_profile?: string | null;
    context_origin?: string | null;
    live_history_turns?: number | null;
    mandatory_static_injections?: string[];
    optional_static_injections?: string[];
    estimate?: {
      total_tokens?: number | null;
      reserve_tokens?: number | null;
      available_tokens?: number | null;
      gross_prompt_tokens?: number | null;
      current_prompt_tokens?: number | null;
      cached_prompt_tokens?: number | null;
      completion_tokens?: number | null;
      utilization?: number | null;
      source?: string | null;
    } | null;
    usage?: {
      total_tokens?: number | null;
      gross_prompt_tokens?: number | null;
      current_prompt_tokens?: number | null;
      cached_prompt_tokens?: number | null;
      completion_tokens?: number | null;
      utilization?: number | null;
      source?: string | null;
    } | null;
  } | null;
  disclaimer: string;
}

// Prompt Template types
export interface PromptTemplate {
  id: string;
  name: string;
  description?: string | null;
  content: string;
  category?: string | null;
  tags: string[];
  group?: string | null;
  recommended_heartbeat?: {
    prompt: string;
    interval: string;
    quiet_start?: string | null;
    quiet_end?: string | null;
  } | null;
  workspace_id?: string | null;
  source_type: string;
  source_path?: string | null;
  created_at: string;
  updated_at: string;
}

// Cron job types
export interface CronEntry {
  expression: string;
  command: string;
  source_type: "container" | "host";
  source_name: string;
  workspace_id?: string | null;
  workspace_name?: string | null;
  user: string;
}

// Heartbeat types
export interface HeartbeatHistoryRun {
  id: string;
  status: string;
  run_at: string;
  completed_at?: string | null;
  result?: string | null;
  error?: string | null;
  correlation_id?: string | null;
  repetition_detected?: boolean | null;
  tool_calls: { tool_name: string; tool_type: string; iteration?: number | null; duration_ms?: number | null; error?: string | null }[];
  total_tokens: number;
  iterations: number;
  duration_ms?: number | null;
}

// Spike alert types
export interface SpikeConfig {
  id: string;
  enabled: boolean;
  window_minutes: number;
  baseline_hours: number;
  relative_threshold: number;
  absolute_threshold_usd: number;
  cooldown_minutes: number;
  targets: SpikeTarget[];
  target_ids: string[];
  last_alert_at: string | null;
  last_check_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SpikeTarget {
  type: "channel" | "integration";
  channel_id?: string;
  integration_type?: string;
  client_id?: string;
  label?: string;
}

export interface SpikeStatus {
  enabled: boolean;
  spiking: boolean;
  window_rate: number;
  baseline_rate: number;
  spike_ratio: number | null;
  cooldown_active: boolean;
  cooldown_remaining_seconds: number;
}

export interface SpikeAlert {
  id: string;
  window_rate_usd_per_hour: number;
  baseline_rate_usd_per_hour: number;
  spike_ratio: number | null;
  trigger_reason: string;
  top_models: { model: string; cost: number; calls: number }[];
  top_bots: { bot_id: string; cost: number }[];
  recent_traces: { correlation_id: string; model: string; bot_id: string; cost: number }[];
  targets_attempted: number;
  targets_succeeded: number;
  delivery_details: { target: SpikeTarget; success: boolean; error?: string }[];
  created_at: string | null;
}

export interface SpikeAlertList {
  total: number;
  page: number;
  page_size: number;
  alerts: SpikeAlert[];
}

export interface TargetOption {
  type: "channel" | "integration";
  channel_id?: string;
  integration_type?: string;
  client_id?: string;
  label: string;
}

export interface AvailableIntegration {
  integration_type: string;
  client_id_prefix: string;
}

export interface AvailableTargetsResponse {
  options: TargetOption[];
  integrations: AvailableIntegration[];
}

export type NotificationTargetKind = "user_push" | "channel" | "integration_binding" | "group";

export interface NotificationTarget {
  id: string;
  slug: string;
  label: string;
  kind: NotificationTargetKind;
  config: Record<string, any>;
  enabled: boolean;
  allowed_bot_ids: string[];
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface NotificationTargetCreate {
  label: string;
  kind: NotificationTargetKind;
  slug?: string;
  config?: Record<string, any>;
  enabled?: boolean;
  allowed_bot_ids?: string[];
}

export interface NotificationTargetUpdate {
  label?: string;
  kind?: NotificationTargetKind;
  slug?: string;
  config?: Record<string, any>;
  enabled?: boolean;
  allowed_bot_ids?: string[];
}

export interface NotificationDestination {
  kind: NotificationTargetKind;
  label: string;
  config: Record<string, any>;
  description?: string;
}

export interface NotificationTargetDestinations {
  options: NotificationDestination[];
  integrations: AvailableIntegration[];
}

export interface NotificationDelivery {
  id: string;
  target_id: string | null;
  root_target_id: string | null;
  sender_type: string;
  sender_id: string | null;
  title: string;
  body_preview: string;
  url: string | null;
  severity: string;
  tag: string | null;
  attempts: number;
  succeeded: number;
  delivery_details: { target?: { id?: string; label?: string; kind?: string }; success: boolean; error?: string }[];
  created_at: string | null;
}

export interface NotificationDeliveryList {
  total: number;
  page: number;
  page_size: number;
  deliveries: NotificationDelivery[];
}

// Storage / data retention types
export interface TableStats {
  table: string;
  row_count: number;
  size_bytes: number | null;
  size_display: string | null;
  oldest_row: string | null;
  purgeable: number;
}

export interface StorageBreakdown {
  tables: TableStats[];
  retention_days: number | null;
  sweep_interval_s: number;
}

export interface PurgeResult {
  deleted: Record<string, number>;
  total: number;
}

// Docker Stacks
export interface DockerStack {
  id: string;
  name: string;
  description?: string | null;
  created_by_bot: string;
  channel_id?: string | null;
  compose_definition: string;
  project_name: string;
  status: string;
  error_message?: string | null;
  network_name?: string | null;
  container_ids: Record<string, string>;
  exposed_ports: Record<string, Array<{ host_port: number; container_port: number; protocol?: string }>>;
  source: string;
  integration_id?: string | null;
  last_started_at?: string | null;
  last_stopped_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DockerStackServiceStatus {
  name: string;
  state: string;
  health?: string | null;
  ports: Array<{ host_port: number; container_port: number; protocol?: string }>;
}

// Admin types
export interface AdminStats {
  sessions: number;
  tools: number;
  sandboxes: number;
}
