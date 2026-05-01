"""Project coding-run facade.

This module is a thin re-export layer over four canonical owners:

- ``project_coding_run_lib`` — shared types, helpers, read endpoints
- ``project_coding_run_orchestration`` — create + continue
- ``project_coding_run_review`` — review session + finalize + cleanup
- ``project_run_schedule`` — schedule CRUD + firing + listing

Every public name that callers import from ``app.services.project_coding_runs``
keeps working, so routers, the workspace launcher, the trigger host, and
existing tests don't move. New code should import from the canonical owner
directly.

The architecture guard ``test_project_coding_run_split_architecture.py`` pins
this file to a re-export-only shape: no function/class definitions live here.
"""
from __future__ import annotations

# noqa: F401 throughout — these are re-exports, not unused imports.

from app.services.project_task_execution_context import (  # noqa: F401
    ProjectTaskExecutionContext,
)
from app.services.project_coding_run_lib import (  # noqa: F401
    DEFAULT_DEV_TARGET_PORT_RANGE,
    PROJECT_CODING_RUN_PRESET_ID,
    PROJECT_CODING_RUN_REVIEW_PRESET_ID,
    PROJECT_CODING_RUN_SCHEDULE_PRESET_ID,
    PROJECT_REVIEW_TEMPLATE_MARKER,
    ProjectCodingRunContinue,
    ProjectCodingRunCreate,
    ProjectCodingRunReviewCreate,
    ProjectCodingRunReviewFinalize,
    ProjectCodingRunScheduleCreate,
    ProjectCodingRunScheduleUpdate,
    ProjectMachineTargetGrant,
    _activity_receipts,
    _attach_task_machine_grant,
    _coding_run_row,
    _dev_target_env,
    _dev_target_specs,
    _evidence_summary,
    _execution_config_from_preset,
    _first_repo,
    _is_port_listening,
    _latest_action,
    _latest_run_receipts_by_task,
    _lineage_config,
    _load_project_coding_task,
    _machine_access_prompt_block,
    _machine_target_grant_summary,
    _prior_evidence_context,
    _project_repo_cwd,
    _receipt_summary,
    _review_summary,
    _review_task_config,
    _run_status,
    _safe_dependency_stack_target,
    _safe_runtime_target,
    _slug,
    _step_result,
    _step_status,
    _summarize_checks,
    _task_run_config,
    _task_summary,
    _utcnow,
    _uuid_from_config,
    allocate_project_run_dev_targets,
    get_project_coding_run,
    list_project_coding_run_review_batches,
    list_project_coding_runs,
    project_coding_run_defaults,
    refresh_project_coding_run_status,
)
from app.services.project_coding_run_orchestration import (  # noqa: F401
    _next_continuation_index,
    _project_coding_run_prompt,
    continue_project_coding_run,
    create_project_coding_run,
)
from app.services.project_coding_run_review import (  # noqa: F401
    _evidence_summary_for_prompt,
    _load_project_review_task,
    _normal_merge_method,
    _normal_review_outcome,
    _record_review_marked,
    _record_review_result,
    _review_context_readiness,
    _review_context_row,
    _review_error_payload,
    _review_session_config,
    _selected_runs_prompt_block,
    _substitute_review_template_variables,
    cleanup_project_coding_run_instance,
    create_project_coding_run_review_session,
    expand_project_review_prompt_template,
    finalize_project_coding_run_review,
    get_project_coding_run_review_context,
    mark_project_coding_run_reviewed,
    mark_project_coding_runs_reviewed,
)
from app.services.project_run_schedule import (  # noqa: F401
    _coding_run_schedule_row,
    _is_project_coding_run_schedule,
    _project_schedule_config,
    _schedule_execution_config,
    _validate_schedule_channel,
    create_project_coding_run_schedule,
    disable_project_coding_run_schedule,
    fire_project_coding_run_schedule,
    list_project_coding_run_schedules,
    update_project_coding_run_schedule,
)
