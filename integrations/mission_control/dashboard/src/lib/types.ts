/** Core domain types for Mission Control. */

// ---------------------------------------------------------------------------
// Kanban / Tasks
// ---------------------------------------------------------------------------

export interface TaskCard {
  title: string;
  meta: Record<string, string>;
  description: string;
}

export interface KanbanCard extends TaskCard {
  channel_id: string;
  channel_name: string;
}

export interface KanbanColumn {
  name: string;
  cards: TaskCard[];
}

export interface AggregatedKanbanColumn {
  name: string;
  cards: KanbanCard[];
}

// ---------------------------------------------------------------------------
// API data (matches /integrations/mission_control/overview response)
// ---------------------------------------------------------------------------

export interface ChannelSummary {
  id: string;
  name: string | null;
  bot_id: string | null;
  bot_name: string | null;
  model: string | null;
  workspace_enabled: boolean;
  task_count: number;
  template_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  is_member: boolean;
}

export interface BotSummary {
  id: string;
  name: string;
  model: string | null;
  channel_count: number;
  memory_scheme: string | null;
}

export interface OverviewData {
  channels: ChannelSummary[];
  bots: BotSummary[];
  total_channels: number;
  total_channels_all: number;
  total_bots: number;
  total_tasks: number;
  is_admin: boolean;
}

// ---------------------------------------------------------------------------
// File system
// ---------------------------------------------------------------------------

export interface WorkspaceFile {
  name: string;
  path: string;
  size: number;
  modified_at: number;
  section: "active" | "archive" | "data";
}

export interface DailyLog {
  date: string;
  content: string;
}

export interface FileChannel {
  id: string;
  display_name?: string;
  name?: string | null;
  bot_id?: string | null;
  workspace_enabled?: boolean;
}

// ---------------------------------------------------------------------------
// Journal
// ---------------------------------------------------------------------------

export interface JournalEntry {
  date: string;
  bot_id: string;
  bot_name: string;
  content: string;
}

// ---------------------------------------------------------------------------
// Timeline
// ---------------------------------------------------------------------------

export interface TimelineEvent {
  date: string;
  time: string;
  event: string;
  channel_id: string;
  channel_name: string;
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export interface MemorySection {
  bot_id: string;
  bot_name: string;
  memory_content: string | null;
  reference_files: string[];
}

// ---------------------------------------------------------------------------
// Plans
// ---------------------------------------------------------------------------

export interface PlanStep {
  position: number;
  status: string;
  content: string;
  requires_approval: boolean;
  task_id: string | null;
  result_summary: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface Plan {
  id: string;
  title: string;
  status: string;
  meta: Record<string, string>;
  steps: PlanStep[];
  notes: string;
  channel_id: string;
  channel_name: string;
  created_at: string | null;
  updated_at: string | null;
}

// ---------------------------------------------------------------------------
// Preferences
// ---------------------------------------------------------------------------

export interface MCPrefs {
  tracked_channel_ids: string[] | null;
  tracked_bot_ids: string[] | null;
  kanban_filters: Record<string, unknown>;
  layout_prefs: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Readiness
// ---------------------------------------------------------------------------

export interface FeatureReadiness {
  ready: boolean;
  detail: string;
  count: number;
  total: number;
  issues: string[];
}

export interface ReadinessData {
  dashboard: FeatureReadiness;
  kanban: FeatureReadiness;
  journal: FeatureReadiness;
  memory: FeatureReadiness;
  timeline: FeatureReadiness;
  plans: FeatureReadiness;
}

// ---------------------------------------------------------------------------
// Channel Context (debug)
// ---------------------------------------------------------------------------

export interface ChannelContext {
  config: {
    channel_id: string;
    channel_name: string;
    bot_id: string;
    bot_name: string;
    model: string;
    workspace_enabled: boolean;
    workspace_rag: boolean;
    context_compaction: boolean;
    memory_scheme: string | null;
    history_mode: string | null;
    tools: string[];
    mcp_servers: string[];
    skills: string[];
    pinned_tools: string[];
  };
  schema: {
    template_name: string | null;
    content: string | null;
  };
  files: Array<{
    name: string;
    path: string;
    size: number;
    modified_at: number;
    section: string;
  }>;
  tool_calls: Array<{
    id: string;
    tool_name: string;
    tool_type: string;
    arguments: Record<string, unknown>;
    result: string;
    error: string | null;
    duration_ms: number | null;
    created_at: string | null;
  }>;
  trace_events: Array<{
    id: string;
    event_type: string;
    event_name: string | null;
    data: Record<string, unknown> | null;
    duration_ms: number | null;
    created_at: string | null;
  }>;
}
