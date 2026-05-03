import type {
  ProjectCodingRun,
  ProjectCodingRunReviewBatch,
  ProjectCodingRunReviewSessionLedger,
  ProjectCodingRunSchedule,
  ProjectFactoryReviewInboxItem,
} from "@/src/types/api";

export type BoardColumnKey = "backlog" | "running" | "review" | "closed";

export type BoardItem =
  | { id: string; kind: "run"; column: BoardColumnKey; run: ProjectCodingRun }
  | { id: string; kind: "schedule"; column: "schedule"; schedule: ProjectCodingRunSchedule }
  | { id: string; kind: "review_session"; column: "review"; session: ProjectCodingRunReviewSessionLedger }
  | { id: string; kind: "batch"; column: "backlog"; batch: ProjectCodingRunReviewBatch }
  | { id: string; kind: "inbox"; column: "backlog"; item: ProjectFactoryReviewInboxItem }
  | { id: string; kind: "new_run"; column: "backlog" }
  | { id: string; kind: "new_schedule"; column: "schedule" };

export type FeedItem =
  | { id: string; kind: "schedule"; group: "upcoming"; schedule: ProjectCodingRunSchedule }
  | { id: string; kind: "run"; group: "active" | "history"; run: ProjectCodingRun };

export const BOARD_COLUMNS: BoardColumnKey[] = ["backlog", "running", "review", "closed"];

const TERMINAL_STATUSES = new Set(["complete", "completed", "cancelled", "canceled", "failed"]);
const STALE_ACTIVE_MS = 30 * 60 * 1000;

function toTime(value?: string | null) {
  if (!value) return Number.POSITIVE_INFINITY;
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : Number.POSITIVE_INFINITY;
}

export function runTitle(run: ProjectCodingRun) {
  return run.task.title || "Project coding run";
}

export function runDescription(run: ProjectCodingRun) {
  return run.request || "";
}

export function shortId(value?: string | null) {
  if (!value) return "";
  const parts = value.split(":");
  return (parts[1] || value).slice(0, 8);
}

export function runStatus(run: ProjectCodingRun) {
  return String(run.task?.status || run.status || "").toLowerCase();
}

export function reviewStatus(run: ProjectCodingRun) {
  return String(run.review_queue_state || run.review?.status || run.status || "").toLowerCase();
}

export function isActiveRun(run: ProjectCodingRun) {
  const status = runStatus(run);
  return status === "pending" || status === "running";
}

export function isClosedRun(run: ProjectCodingRun) {
  const status = runStatus(run);
  const review = reviewStatus(run);
  return TERMINAL_STATUSES.has(status) || review === "reviewed" || Boolean(run.review?.reviewed);
}

export function isReviewRun(run: ProjectCodingRun) {
  if (isClosedRun(run)) return false;
  const review = reviewStatus(run);
  return ["blocked", "changes_requested", "ready_for_review", "needs_review", "missing_evidence", "pending_evidence", "reviewing", "follow_up_running"].includes(review);
}

export function isActiveReviewSession(session: ProjectCodingRunReviewSessionLedger) {
  const status = String(session.task_status || session.status || "").toLowerCase();
  return Boolean(session.actions?.active) || status === "pending" || status === "running" || status === "active";
}

export function itemTimestamp(run: ProjectCodingRun) {
  return run.updated_at || run.task.completed_at || run.created_at || run.task.created_at || null;
}

export function startedTimestamp(run: ProjectCodingRun) {
  return run.created_at || run.task.created_at || run.task.run_at || null;
}

export function ageMs(value?: string | null, nowMs = Date.now()) {
  if (!value) return 0;
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return 0;
  return Math.max(0, nowMs - time);
}

export function isStaleActive(run: ProjectCodingRun, nowMs = Date.now()) {
  return isActiveRun(run) && ageMs(itemTimestamp(run) || startedTimestamp(run), nowMs) > STALE_ACTIVE_MS && !run.receipt;
}

export function evidenceLine(run: ProjectCodingRun) {
  const evidence = run.review?.evidence;
  if (evidence) {
    return `${evidence.tests_count ?? 0} tests · ${evidence.screenshots_count ?? 0} screenshots · ${evidence.changed_files_count ?? 0} files`;
  }
  if (!run.receipt) return "no receipt";
  return `${run.receipt.tests?.length ?? 0} tests · ${run.receipt.screenshots?.length ?? 0} screenshots · ${run.receipt.changed_files?.length ?? 0} files`;
}

export function classifyRun(run: ProjectCodingRun): BoardColumnKey {
  if (isClosedRun(run)) return "closed";
  if (isActiveRun(run)) return "running";
  if (isReviewRun(run)) return "review";
  return "backlog";
}

function itemPriority(item: BoardItem) {
  if (item.kind === "run") {
    if (isStaleActive(item.run)) return 0;
    const review = reviewStatus(item.run);
    if (review === "blocked" || review === "changes_requested") return 1;
    if (isActiveRun(item.run)) return 2;
    if (isReviewRun(item.run)) return 3;
    if (isClosedRun(item.run)) return 8;
    return 5;
  }
  if (item.kind === "review_session") return item.session.actions?.active ? 2 : 6;
  if (item.kind === "batch") return 5;
  if (item.kind === "inbox") return 5;
  return 9;
}

function itemSortTime(item: BoardItem) {
  if (item.kind === "run") return itemTimestamp(item.run) || "";
  if (item.kind === "review_session") return item.session.latest_activity_at || item.session.created_at || "";
  if (item.kind === "inbox") return item.item.updated_at || item.item.created_at || "";
  return "";
}

function scheduleRank(schedule: ProjectCodingRunSchedule) {
  if (!schedule.enabled) return 2;
  return Number.isFinite(toTime(schedule.scheduled_at)) ? 0 : 1;
}

export function sortScheduleRailItems(schedules: ProjectCodingRunSchedule[]): BoardItem[] {
  const items = schedules
    .map((schedule): Extract<BoardItem, { kind: "schedule" }> => ({ id: `schedule:${schedule.id}`, kind: "schedule", column: "schedule", schedule }))
    .sort((a, b) => {
      const rank = scheduleRank(a.schedule) - scheduleRank(b.schedule);
      if (rank !== 0) return rank;
      const time = toTime(a.schedule.scheduled_at) - toTime(b.schedule.scheduled_at);
      if (time !== 0 && Number.isFinite(time)) return time;
      return String(a.schedule.title || "").localeCompare(String(b.schedule.title || ""));
    });
  return [{ id: "action:new-schedule", kind: "new_schedule", column: "schedule" }, ...items];
}

export function buildBoardItems({
  runs,
  reviewBatches,
  reviewSessions,
  inboxItems,
}: {
  runs: ProjectCodingRun[];
  reviewBatches: ProjectCodingRunReviewBatch[];
  reviewSessions: ProjectCodingRunReviewSessionLedger[];
  inboxItems: ProjectFactoryReviewInboxItem[];
}) {
  const items: BoardItem[] = [
    { id: "action:new-run", kind: "new_run", column: "backlog" },
    ...reviewSessions.filter(isActiveReviewSession).map((session) => ({ id: `review-session:${session.id}`, kind: "review_session" as const, column: "review" as const, session })),
    ...runs.map((run) => ({ id: `run:${run.id}`, kind: "run" as const, column: classifyRun(run), run })),
    ...reviewBatches.filter((batch) => batch.status !== "reviewed").map((batch) => ({ id: `batch:${batch.id}`, kind: "batch" as const, column: "backlog" as const, batch })),
    ...inboxItems.map((item) => ({ id: `inbox:${item.id}`, kind: "inbox" as const, column: "backlog" as const, item })),
  ];
  return items.sort((a, b) => {
    const priority = itemPriority(a) - itemPriority(b);
    if (priority !== 0) return priority;
    return itemSortTime(b).localeCompare(itemSortTime(a));
  });
}

export function groupBoardColumns(boardItems: BoardItem[]) {
  const map: Record<BoardColumnKey, BoardItem[]> = { backlog: [], running: [], review: [], closed: [] };
  for (const item of boardItems) {
    if (item.column !== "schedule") map[item.column].push(item);
  }
  return map;
}

export function buildFeedItems({
  runs,
  schedules,
}: {
  runs: ProjectCodingRun[];
  schedules: ProjectCodingRunSchedule[];
}): FeedItem[] {
  const upcoming = schedules
    .map((schedule): FeedItem => ({ id: `schedule:${schedule.id}`, kind: "schedule", group: "upcoming", schedule }))
    .sort((a, b) => {
      if (a.kind !== "schedule" || b.kind !== "schedule") return 0;
      const rank = scheduleRank(a.schedule) - scheduleRank(b.schedule);
      if (rank !== 0) return rank;
      return toTime(a.schedule.scheduled_at) - toTime(b.schedule.scheduled_at);
    });
  const active = runs
    .filter((run) => !isClosedRun(run))
    .map((run): FeedItem => ({ id: `run:${run.id}`, kind: "run", group: "active", run }))
    .sort((a, b) => (b.kind === "run" && a.kind === "run" ? String(itemTimestamp(b.run) || "").localeCompare(String(itemTimestamp(a.run) || "")) : 0));
  const history = runs
    .filter(isClosedRun)
    .map((run): FeedItem => ({ id: `run:${run.id}`, kind: "run", group: "history", run }))
    .sort((a, b) => (b.kind === "run" && a.kind === "run" ? String(itemTimestamp(b.run) || "").localeCompare(String(itemTimestamp(a.run) || "")) : 0));
  return [...upcoming, ...active, ...history];
}
