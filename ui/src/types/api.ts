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
  tool_groups: ToolGroup[];
  mcp_servers: string[];
  client_tools: string[];
  all_skills: SkillOption[];
  all_bots: { id: string; name: string }[];
  all_sandbox_profiles: { name: string; description?: string }[];
  model_param_definitions: ModelParamDefinition[];
  model_param_support: Record<string, string[]>;
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

// Chat HUD — integration-declared widgets in chat view
export interface HudOnClick {
  type: "link" | "action" | "refresh";
  href?: string;
  endpoint?: string;
  method?: string;
  body?: Record<string, any>;
  confirm?: string;
}

export interface HudItem {
  type: "badge" | "action" | "divider" | "text" | "progress" | "group";
  label?: string;
  value?: string;
  icon?: string;
  variant?: "default" | "success" | "warning" | "danger" | "accent" | "muted";
  on_click?: HudOnClick;
  max?: number; // for progress items
  items?: HudItem[]; // for group items
}

export interface HudData {
  visible: boolean;
  items: HudItem[];
}

export interface ChatHudWidget {
  id: string;
  style: "status_strip" | "side_panel" | "input_bar" | "floating_action";
  endpoint?: string;
  iframe_path?: string;
  poll_interval?: number;
  label?: string;
  icon?: string;
  width?: number;
  collapsed_by_default?: boolean;
  on_click?: HudOnClick;
  badge_endpoint?: string;
}

// Integration activation
export interface ChatHudPreset {
  label: string;
  widgets: string[];
  description?: string;
}

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
  chat_hud?: ChatHudWidget[];
  chat_hud_presets?: Record<string, ChatHudPreset>;
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
    /** Channel-scoped HTML widget SDK theme override. */
    widget_theme_ref?: string | null;
  };
  category?: string | null;
  tags?: string[];
  last_message_at?: string | null;
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
  envelope: ToolResultEnvelope;
  position: number;
  pinned_at: string;
  /** Per-pin user config — shallow-merged over the template's default_config
   *  and exposed as `{{config.*}}` in widget + state_poll templates. Flipped
   *  via `{dispatch: "widget_config"}` actions. */
  config?: Record<string, unknown>;
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
  available_actions?: Array<{
    id: string;
    description?: string;
    args_schema?: Record<string, unknown>;
    returns_schema?: Record<string, unknown> | null;
  }>;
  pinned_at: string | null;
  updated_at: string | null;
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
  /** Channel-scoped HTML widget SDK theme override. Null/absent inherits the global default. */
  widget_theme_ref?: string | null;
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

export type SlashCommandId = "stop" | "context" | "clear" | "compact" | "scratch" | "plan";
export type SlashCommandSurface = "channel" | "session";

export interface SlashCommandResult {
  command_id: string;
  result_type: string;
  payload: Record<string, any>;
  fallback_text: string;
}

export interface SlashCommandSideEffectPayload {
  effect: "stop" | "compact" | "plan";
  scope_kind: "channel" | "session";
  scope_id: string;
  title: string;
  detail: string;
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
  content_type: string;
  body: string | Record<string, unknown> | null;
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
  categories: ContextCategory[];
  total_chars: number;
  total_tokens_approx: number;
  compaction: CompactionState;
  compression?: CompressionState | null;
  reranking: RerankState;
  effective_settings: Record<string, EffectiveSetting>;
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
