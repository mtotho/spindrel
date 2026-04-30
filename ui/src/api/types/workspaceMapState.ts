export type WorkspaceMapObjectKind = "channel" | "project" | "bot" | "widget" | "landmark" | "object";
export type WorkspaceMapObjectStatus =
  | "idle"
  | "recent"
  | "scheduled"
  | "active"
  | "running"
  | "warning"
  | "error";
export type WorkspaceMapSeverity = "info" | "warning" | "error" | "critical";
export type WorkspaceMapCueIntent = "investigate" | "next" | "recent" | "quiet";

export interface WorkspaceMapCue {
  intent: WorkspaceMapCueIntent;
  label: string;
  reason: string;
  priority: number;
  target_surface: string;
  signal_kind?: string | null;
  signal_title?: string | null;
}

export interface WorkspaceMapSignal {
  id?: string;
  kind: string;
  title?: string | null;
  status?: string | null;
  severity?: WorkspaceMapSeverity | null;
  message?: string | null;
  task_id?: string | null;
  bot_id?: string | null;
  bot_name?: string | null;
  channel_id?: string | null;
  channel_name?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  correlation_id?: string | null;
  scheduled_at?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  last_seen_at?: string | null;
  error?: string | null;
  result?: string | null;
}

export interface WorkspaceMapObjectState {
  node_id: string;
  kind: WorkspaceMapObjectKind;
  target_id: string;
  label: string;
  status: WorkspaceMapObjectStatus;
  severity?: WorkspaceMapSeverity | null;
  primary_signal?: string | null;
  secondary_signal?: string | null;
  counts: {
    upcoming: number;
    recent: number;
    warnings: number;
    widgets: number;
    integrations: number;
    bots: number;
    channels?: number;
  };
  next?: WorkspaceMapSignal | null;
  recent: WorkspaceMapSignal[];
  warnings: WorkspaceMapSignal[];
  cue?: WorkspaceMapCue | null;
  source: Record<string, unknown>;
  attached: Record<string, unknown>;
}

export interface WorkspaceMapState {
  generated_at?: string | null;
  source: "existing_primitives";
  summary: {
    objects: number;
    channels: number;
    projects: number;
    bots: number;
    widgets: number;
    landmarks: number;
    warnings: number;
    upcoming: number;
    recent: number;
  };
  objects: WorkspaceMapObjectState[];
  objects_by_node_id: Record<string, WorkspaceMapObjectState>;
  upcoming: WorkspaceMapSignal[];
  recent: WorkspaceMapSignal[];
}
