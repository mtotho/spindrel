---
status: reference
updated: 2026-04-17
tags:
  - testing
  - audit
  - coverage
---

# Test Audit — Coverage Gaps

Coverage audit of `app/services/` public (imported-elsewhere) functions and `app/routers/` FastAPI routes. Generated 2026-04-17 by static analysis:

- **Public service symbols**: module-level `def` / `async def` imported by at least one other module under `app/` or `integrations/`.
- **Routes**: `@router.<method>(...)` / `@app.<method>(...)` decorators in `app/routers/**`.
- **Covered**: at least one test file under `tests/unit/` or `tests/integration/` imports the symbol (or references the route path) AND uses a real `db_session` / `AsyncClient` / `ASGITransport` / `TestClient`.
- **Mock-only**: test files reference the symbol but only with `MagicMock` / `AsyncMock` — per `testing-python/SKILL.md` E.13 this is "nearly equivalent to no coverage" because a mocked `Session` silently accepts nonsense queries.
- **Uncovered**: no test file imports the symbol or exercises the path.

Risk heuristic: names containing `create/delete/update/send/dispatch/publish/encrypt/execute/enroll/activate/…` → critical; read/list/search/get → high; other internal reads → medium. Route: any non-GET method → critical.

## Summary Counts

**Services** — 247 public symbols across 84 modules:

| risk | covered | mock-only | uncovered | total |
|------|---------|-----------|-----------|-------|
| critical | 42 | 8 | 25 | 75 |
| high | 43 | 10 | 29 | 82 |
| medium | 37 | 15 | 38 | 90 |

**Routes** — 355 endpoints across 55 router files:

| risk | covered | mock-only | uncovered | total |
|------|---------|-----------|-----------|-------|
| critical | 106 | 4 | 60 | 170 |
| high | 7 | 0 | 10 | 17 |
| medium | 108 | 3 | 57 | 168 |

**Aggregate gaps**: 219 uncovered, 40 mock-only, 343 well-covered.

## Top 10 Highest-Priority Gaps

Critical tier, uncovered first, then mock-only. These mutate data, handle auth, or send external messages — most likely to produce silent production bugs.

| # | kind | location | symbol/path | status |
|---|------|----------|-------------|--------|
| 1 | route | `app/routers/api_v1_admin/attachments.py` | `DELETE /attachments/{attachment_id}` | uncovered |
| 2 | route | `app/routers/api_v1_admin/attachments.py` | `POST /attachments/purge` | uncovered |
| 3 | route | `app/routers/api_v1_admin/bots.py` | `POST /bots` | uncovered |
| 4 | route | `app/routers/api_v1_admin/bots.py` | `DELETE /bots/{bot_id}` | uncovered |
| 5 | route | `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/memory-hygiene/trigger` | uncovered |
| 6 | route | `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/memory-scheme` | uncovered |
| 7 | route | `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/sandbox/recreate` | uncovered |
| 8 | route | `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/enrolled-skills` | uncovered |
| 9 | route | `app/routers/api_v1_admin/bots.py` | `DELETE /bots/{bot_id}/enrolled-skills/{skill_id:path}` | uncovered |
| 10 | route | `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/enrolled-tools` | uncovered |

## Critical Service Symbols

All 75 critical-tier service symbols. Sorted: covered → mock-only → uncovered.

| module | symbol | status | covering test file(s) |
|--------|--------|--------|-----------------------|
| `api_keys.py` | `create_api_key` | covered | test_api_key_provisioning.py;test_bot_admin.py;test_admin_scoped_auth.py;test... |
| `api_keys.py` | `provision_integration_api_key` | covered | test_api_key_provisioning.py |
| `api_keys.py` | `revoke_integration_api_key` | covered | test_api_key_provisioning.py |
| `attachments.py` | `create_attachment` | covered | test_attachment_retention.py;test_attachment_service.py |
| `auth.py` | `create_local_user` | covered | test_api_key_provisioning.py |
| `channel_events.py` | `publish_typed` | covered | test_outbox_drainer.py;test_compaction_comprehensive.py;test_workflow_recover... |
| `channel_workspace.py` | `write_workspace_file` | covered | test_mission_control.py |
| `channels.py` | `apply_channel_visibility` | covered | test_channel_ownership.py |
| `channels.py` | `get_or_create_channel` | covered | test_channel_protected.py;test_channel_members.py;test_channel_bot_overwrite.... |
| `compaction.py` | `run_compaction_forced` | covered | test_compaction_logging.py;test_compaction_comprehensive.py |
| `config_export.py` | `restore_from_file` | covered | test_config_export.py |
| `encryption.py` | `decrypt` | covered | test_mcp_servers.py |
| `encryption.py` | `encrypt` | covered | test_mcp_servers.py |
| `integration_settings.py` | `delete_setting` | covered | test_integration_settings.py |
| `integration_settings.py` | `update_settings` | covered | test_integration_settings.py |
| `memory_hygiene.py` | `bootstrap_hygiene_schedule` | covered | test_memory_hygiene.py |
| `memory_hygiene.py` | `create_hygiene_task` | covered | test_memory_hygiene.py |
| `memory_hygiene.py` | `resolve_enabled` | covered | test_memory_hygiene.py |
| `providers.py` | `has_encrypted_secrets` | covered | test_encryption_enforcement.py |
| `secret_values.py` | `update_secret` | covered | test_secret_values.py |
| `security_audit.py` | `run_security_audit` | covered | test_security_audit.py |
| `sessions.py` | `load_or_create` | covered | test_tasks.py;test_tasks.py;test_sessions.py |
| `sessions.py` | `persist_turn` | covered | test_tasks.py;test_multi_bot_channels.py;test_message_metadata_tool_results.p... |
| `sessions.py` | `store_dispatch_echo` | covered | test_delegation.py |
| `sessions.py` | `store_passive_message` | covered | test_sessions.py |
| `skill_enrollment.py` | `enroll` | covered | test_skill_enrollment.py |
| `skill_enrollment.py` | `enroll_starter_pack` | covered | test_skill_enrollment.py |
| `skill_enrollment.py` | `invalidate_enrolled_cache` | covered | test_skill_enrollment.py;test_context_assembly.py |
| `skill_enrollment.py` | `unenroll` | covered | test_skill_enrollment.py |
| `skill_enrollment.py` | `unenroll_many` | covered | test_skill_enrollment.py |
| `step_executor.py` | `run_task_pipeline` | covered | test_step_executor.py |
| `tool_enrollment.py` | `enroll` | covered | test_tool_enrollment.py |
| `tool_enrollment.py` | `enroll_many` | covered | test_tool_enrollment.py |
| `tool_enrollment.py` | `enroll_starter_tools` | covered | test_tool_enrollment.py |
| `tool_enrollment.py` | `get_enrolled_tool_names` | covered | test_tool_enrollment.py |
| `tool_enrollment.py` | `get_enrollments` | covered | test_tool_enrollment.py |
| `tool_enrollment.py` | `unenroll` | covered | test_tool_enrollment.py |
| `tool_enrollment.py` | `unenroll_many` | covered | test_tool_enrollment.py |
| `turns.py` | `start_turn` | covered | test_session_status.py;test_attachments.py |
| `workflows.py` | `delete_workflow` | covered | test_workflow_improvements.py |
| `workflows.py` | `update_workflow` | covered | test_workflow_improvements.py |
| `workspace_bootstrap.py` | `ensure_all_bots_enrolled` | covered | test_workspace_bootstrap.py |
| `channel_workspace.py` | `delete_workspace_file` | mock-only | test_channel_workspace.py |
| `file_sync.py` | `sync_all_files` | mock-only | test_integration_reload.py |
| `memory_scheme.py` | `bootstrap_memory_scheme` | mock-only | test_memory_scheme.py |
| `secret_values.py` | `create_secret` | mock-only | test_secret_redaction_integration.py |
| `secret_values.py` | `delete_secret` | mock-only | test_secret_redaction_integration.py |
| `server_settings.py` | `reset_setting` | mock-only | test_server_settings.py |
| `server_settings.py` | `update_settings` | mock-only | test_server_settings.py |
| `turn_worker.py` | `run_turn` | mock-only | test_turn_worker.py |
| `attachments.py` | `delete_attachment` | uncovered | — |
| `bot_hooks.py` | `create_hook` | uncovered | — |
| `bot_hooks.py` | `delete_hook` | uncovered | — |
| `bot_hooks.py` | `run_after_exec` | uncovered | — |
| `bot_hooks.py` | `run_before_access` | uncovered | — |
| `bot_hooks.py` | `schedule_after_write` | uncovered | — |
| `bot_hooks.py` | `update_hook` | uncovered | — |
| `channel_events.py` | `publish_message` | uncovered | test_channel_events.py |
| `channel_events.py` | `publish_message_updated` | uncovered | test_channel_events.py |
| `encryption.py` | `is_encryption_enabled` | uncovered | test_encryption.py |
| `integration_manifests.py` | `set_detected_provides` | covered | test_integration_manifests.py |
| `integration_manifests.py` | `update_manifest` | covered | test_integration_manifests.py |
| `outbox.py` | `reset_stale_in_flight` | uncovered | — |
| `outbox_drainer.py` | `outbox_drainer_worker` | uncovered | — |
| `outbox_publish.py` | `publish_to_bus` | uncovered | — |
| `server_config.py` | `update_global_fallback_models` | uncovered | — |
| `server_config.py` | `update_model_tiers` | uncovered | — |
| `sessions.py` | `normalize_stored_content` | uncovered | test_session_helpers.py |
| `task_run_anchor.py` | `update_anchor` | uncovered | — |
| `turn_event_emit.py` | `emit_run_stream_events` | uncovered | — |
| `usage_limits.py` | `start_refresh_task` | uncovered | — |
| `usage_spike.py` | `start_spike_refresh_task` | uncovered | — |
| `widget_templates.py` | `apply_widget_template` | uncovered | test_widget_templates.py |
| `workflow_hooks.py` | `register_workflow_hooks` | uncovered | — |
| `workflows.py` | `create_workflow` | uncovered | — |

## High-Tier Service Gaps (read/list/search paths)

39 of 82 high-tier symbols are uncovered or mock-only.

| module | symbol | status | covering |
|--------|--------|--------|----------|
| `attachments.py` | `find_orphan_duplicate` | uncovered | — |
| `bot_hooks.py` | `list_hooks` | uncovered | — |
| `bot_hooks.py` | `load_bot_hooks` | uncovered | — |
| `channel_throttle.py` | `is_throttled` | uncovered | test_channel_throttle.py |
| `context_estimate.py` | `estimate_bot_context` | uncovered | — |
| `disk_usage.py` | `get_full_disk_report` | uncovered | — |
| `integration_manifests.py` | `check_file_drift` | covered | test_integration_manifests.py |
| `integration_manifests.py` | `get_all_manifests` | covered | test_integration_manifests.py |
| `integration_manifests.py` | `get_capabilities` | covered | test_integration_manifests.py |
| `integration_manifests.py` | `get_yaml_content` | covered | test_integration_manifests.py |
| `integration_settings.py` | `load_from_db` | uncovered | — |
| `memory_scheme.py` | `get_memory_index_patterns` | uncovered | — |
| `pinned_panels.py` | `load_pinned_paths` | uncovered | — |
| `providers.py` | `get_available_models_grouped` | uncovered | — |
| `providers.py` | `get_cached_model_info` | uncovered | — |
| `providers.py` | `get_provider` | uncovered | — |
| `providers.py` | `load_providers` | uncovered | — |
| `secret_values.py` | `list_secrets` | uncovered | — |
| `server_config.py` | `get_model_tiers` | uncovered | — |
| `server_settings.py` | `get_all_settings` | uncovered | — |
| `server_settings.py` | `load_settings_from_db` | uncovered | — |
| `usage_limits.py` | `check_usage_limits` | uncovered | — |
| `usage_limits.py` | `get_limits_status` | uncovered | — |
| `usage_limits.py` | `load_limits` | uncovered | — |
| `webhooks.py` | `load_webhook_endpoints` | uncovered | — |
| `widget_templates.py` | `get_state_poll_config` | uncovered | — |
| `widget_templates.py` | `get_widget_template` | uncovered | — |
| `widget_templates.py` | `load_widget_templates_from_manifests` | uncovered | — |
| `workflows.py` | `reload_workflows` | uncovered | — |
| `auth.py` | `get_user_by_id` | mock-only | test_security_fixes.py |
| `channel_workspace.py` | `get_channel_workspace_index_prefix` | mock-only | test_channel_workspace.py |
| `channels.py` | `is_integration_client_id` | mock-only | test_hooks.py |
| `memory_indexing.py` | `get_memory_patterns` | mock-only | test_memory_indexing.py |
| `memory_scheme.py` | `get_memory_index_prefix` | mock-only | test_search_api.py;test_memory_indexing_paths.py;test_shared_workspace_indexi... |
| `memory_scheme.py` | `get_memory_rel_path` | mock-only | test_memory_indexing_paths.py;test_memory_injection.py;test_memory_scheme.py |
| `prompt_resolution.py` | `resolve_prompt_template` | mock-only | test_prompt_resolution.py;test_workspace_schema_injection.py |
| `prompt_resolution.py` | `resolve_workspace_file_prompt` | mock-only | test_prompt_resolution.py |
| `secret_registry.py` | `check_user_input` | mock-only | test_secret_registry.py;test_secret_redaction_integration.py |
| `workflows.py` | `load_workflows` | mock-only | test_integration_reload.py |

**Medium-tier gaps (not listed)**: 53 symbols. These are internal read helpers / computed views; lower priority unless a critical caller depends on one. Full data in `/tmp/service_results.json` at audit time.

## Router Gaps

127 routes have no test file referencing their path; 7 rely on `MagicMock`/`AsyncMock` exclusively.

### Critical (mutating) route gaps — 51 endpoints remaining (9 shipped 2026-04-18)

| router file | method + path | handler | status |
|-------------|---------------|---------|--------|
| `app/routers/api_v1_admin/attachments.py` | `POST /attachments/purge` | `purge_attachments` | uncovered |
| `app/routers/api_v1_admin/attachments.py` | `DELETE /attachments/{attachment_id}` | `delete_attachment` | uncovered |
| `app/routers/api_v1_admin/bots.py` | `POST /bots` | `admin_bot_create` | covered (test_bot_admin.py::TestBotCreate) |
| `app/routers/api_v1_admin/bots.py` | `DELETE /bots/{bot_id}` | `admin_bot_delete` | covered (test_bot_admin.py::TestBotDelete) |
| `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/enrolled-skills` | `admin_bot_enrolled_skill_add` | covered (test_bot_admin.py::TestEnrolledSkills) |
| `app/routers/api_v1_admin/bots.py` | `DELETE /bots/{bot_id}/enrolled-skills/{skill_id:path}` | `admin_bot_enrolled_skill_remove` | covered (test_bot_admin.py::TestEnrolledSkills) |
| `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/enrolled-tools` | `admin_bot_enrolled_tool_add` | covered (test_bot_admin.py::TestEnrolledTools) |
| `app/routers/api_v1_admin/bots.py` | `DELETE /bots/{bot_id}/enrolled-tools/{tool_name:path}` | `admin_bot_enrolled_tool_remove` | covered (test_bot_admin.py::TestEnrolledTools) |
| `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/memory-hygiene/trigger` | `admin_bot_memory_hygiene_trigger` | covered (test_bot_admin.py::TestMemoryHygieneTrigger) |
| `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/memory-scheme` | `admin_bot_enable_memory_scheme` | covered (test_bot_admin.py::TestMemoryScheme) |
| `app/routers/api_v1_admin/bots.py` | `POST /bots/{bot_id}/sandbox/recreate` | `admin_bot_sandbox_recreate` | covered (test_bot_admin.py::TestSandboxRecreate) |
| `app/routers/api_v1_admin/channels.py` | `POST /channels/ensure-orchestrator` | `ensure_orchestrator` | uncovered |
| `app/routers/api_v1_admin/config_state.py` | `POST /config-state/restore` | `restore_config_state` | uncovered |
| `app/routers/api_v1_admin/diagnostics.py` | `POST /diagnostics/reindex` | `diagnostics_reindex` | uncovered |
| `app/routers/api_v1_admin/docker_stacks.py` | `DELETE /docker-stacks/{stack_id}` | `destroy_docker_stack` | uncovered |
| `app/routers/api_v1_admin/docker_stacks.py` | `POST /docker-stacks/{stack_id}/start` | `start_docker_stack` | uncovered |
| `app/routers/api_v1_admin/docker_stacks.py` | `POST /docker-stacks/{stack_id}/stop` | `stop_docker_stack` | uncovered |
| `app/routers/api_v1_admin/fallbacks.py` | `DELETE /fallbacks/cooldowns/{model:path}` | `clear_cooldown` | uncovered |
| `app/routers/api_v1_admin/integrations.py` | `POST /integrations/reload` | `reload_integrations` | uncovered |
| `app/routers/api_v1_admin/limits.py` | `POST /limits/` | `create_limit` | uncovered |
| `app/routers/api_v1_admin/limits.py` | `PUT /limits/{limit_id}` | `update_limit` | uncovered |
| `app/routers/api_v1_admin/limits.py` | `DELETE /limits/{limit_id}` | `delete_limit` | uncovered |
| `app/routers/api_v1_admin/mcp_servers.py` | `POST /mcp-servers` | `admin_create_mcp_server` | uncovered |
| `app/routers/api_v1_admin/mcp_servers.py` | `POST /mcp-servers/test-inline` | `admin_test_mcp_server_inline` | uncovered |
| `app/routers/api_v1_admin/mcp_servers.py` | `PUT /mcp-servers/{server_id}` | `admin_update_mcp_server` | uncovered |
| `app/routers/api_v1_admin/mcp_servers.py` | `DELETE /mcp-servers/{server_id}` | `admin_delete_mcp_server` | uncovered |
| `app/routers/api_v1_admin/mcp_servers.py` | `POST /mcp-servers/{server_id}/test` | `admin_test_mcp_server` | uncovered |
| `app/routers/api_v1_admin/operations.py` | `POST /operations/backup` | `trigger_backup` | uncovered |
| `app/routers/api_v1_admin/operations.py` | `PUT /operations/backup/config` | `update_backup_config` | uncovered |
| `app/routers/api_v1_admin/operations.py` | `POST /operations/pull` | `git_pull` | uncovered |
| `app/routers/api_v1_admin/operations.py` | `POST /operations/restart` | `restart_server` | uncovered |
| `app/routers/api_v1_admin/prompts.py` | `POST /generate-prompt` | `generate_prompt` | uncovered |
| `app/routers/api_v1_admin/providers.py` | `POST /providers` | `admin_create_provider` | covered (test_provider_admin.py::TestCreateProvider) |
| `app/routers/api_v1_admin/providers.py` | `POST /providers/test-inline` | `admin_test_provider_inline` | covered (test_provider_admin.py::TestTestProviderInline) |
| `app/routers/api_v1_admin/providers.py` | `PUT /providers/{provider_id}` | `admin_update_provider` | covered (test_provider_admin.py::TestUpdateProvider) |
| `app/routers/api_v1_admin/providers.py` | `DELETE /providers/{provider_id}` | `admin_delete_provider` | covered (test_provider_admin.py::TestDeleteProvider) |
| `app/routers/api_v1_admin/providers.py` | `POST /providers/{provider_id}/models` | `admin_add_provider_model` | covered (test_provider_admin.py::TestAddProviderModel) |
| `app/routers/api_v1_admin/providers.py` | `DELETE /providers/{provider_id}/models/{model_pk}` | `admin_delete_provider_model` | covered (test_provider_admin.py::TestDeleteProviderModel) |
| `app/routers/api_v1_admin/providers.py` | `POST /providers/{provider_id}/pull-model` | `admin_pull_model` | covered (test_provider_admin.py::TestPullModel) |
| `app/routers/api_v1_admin/providers.py` | `DELETE /providers/{provider_id}/remote-models/{model_name:path}` | `admin_delete_remote_model` | covered (test_provider_admin.py::TestDeleteRemoteModel) |
| `app/routers/api_v1_admin/providers.py` | `POST /providers/{provider_id}/sync-models` | `admin_sync_provider_models` | covered (test_provider_admin.py::TestSyncProviderModels) |
| `app/routers/api_v1_admin/providers.py` | `POST /providers/{provider_id}/test` | `admin_test_provider` | covered (test_provider_admin.py::TestTestProvider) |
| `app/routers/api_v1_admin/secret_values.py` | `POST /secret-values/` | `create_secret_value` | uncovered |
| `app/routers/api_v1_admin/secret_values.py` | `PUT /secret-values/{secret_id}` | `update_secret_value` | uncovered |
| `app/routers/api_v1_admin/secret_values.py` | `DELETE /secret-values/{secret_id}` | `delete_secret_value` | uncovered |
| `app/routers/api_v1_admin/settings.py` | `PUT /global-fallback-models` | `update_global_fallback_models` | uncovered |
| `app/routers/api_v1_admin/settings.py` | `PUT /global-model-tiers` | `update_global_model_tiers` | uncovered |
| `app/routers/api_v1_admin/webhooks.py` | `POST /webhooks` | `admin_create_webhook` | uncovered |
| `app/routers/api_v1_admin/webhooks.py` | `PUT /webhooks/{endpoint_id}` | `admin_update_webhook` | uncovered |
| `app/routers/api_v1_admin/webhooks.py` | `DELETE /webhooks/{endpoint_id}` | `admin_delete_webhook` | uncovered |
| `app/routers/api_v1_admin/webhooks.py` | `POST /webhooks/{endpoint_id}/rotate-secret` | `admin_rotate_webhook_secret` | uncovered |
| `app/routers/api_v1_admin/webhooks.py` | `POST /webhooks/{endpoint_id}/test` | `admin_test_webhook` | uncovered |
| `app/routers/api_v1_attachments.py` | `POST /attachments/upload` | `upload_attachment` | uncovered |
| `app/routers/api_v1_users.py` | `PUT /admin/users/{user_id}` | `update_user` | uncovered |
| `app/routers/api_v1_users.py` | `DELETE /admin/users/{user_id}` | `deactivate_user` | uncovered |
| `app/routers/auth.py` | `POST /auth/google` | `auth_google` | uncovered |
| `app/routers/auth.py` | `POST /auth/logout` | `auth_logout` | uncovered |
| `app/routers/chat/_routes.py` | `POST /chat` | `chat` | uncovered |
| `app/routers/chat/_routes.py` | `POST /chat/cancel` | `chat_cancel` | uncovered |
| `app/routers/transcribe.py` | `POST /transcribe` | `transcribe` | uncovered |

### High-tier route gaps — 10 endpoints

| router file | method + path | handler | status |
|-------------|---------------|---------|--------|
| `app/routers/api_v1_users.py` | `GET /admin/users/identity-suggestions/{integration}` | `identity_suggestions` | uncovered |
| `app/routers/api_v1_admin/providers.py` | `GET /providers` | `admin_list_providers` | uncovered |
| `app/routers/api_v1_admin/providers.py` | `GET /providers/{provider_id}/models` | `admin_list_provider_models` | uncovered |
| `app/routers/api_v1_admin/providers.py` | `GET /providers/{provider_id}` | `admin_get_provider` | uncovered |
| `app/routers/api_v1_admin/providers.py` | `GET /provider-types/{provider_type}/capabilities` | `admin_provider_type_capabilities` | uncovered |
| `app/routers/api_v1_admin/providers.py` | `GET /providers/{provider_id}/capabilities` | `admin_provider_capabilities` | uncovered |
| `app/routers/api_v1_admin/providers.py` | `GET /providers/{provider_id}/remote-models/{model_name:path}/info` | `admin_remote_model_info` | covered (test_provider_admin.py::TestRemoteModelInfo) |
| `app/routers/api_v1_admin/providers.py` | `GET /providers/{provider_id}/running-models` | `admin_running_models` | covered (test_provider_admin.py::TestRunningModels) |
| `app/routers/api_v1_admin/secret_values.py` | `GET /secret-values/` | `list_secret_values` | uncovered |
| `app/routers/api_v1_admin/secret_values.py` | `GET /secret-values/{secret_id}` | `get_secret_value` | uncovered |

### Mock-only routes — 7 endpoints

| router file | method + path | handler | covering |
|-------------|---------------|---------|----------|
| `app/routers/api_v1_tool_policies.py` | `GET /tool-policies/tiers` | `list_tool_tiers` | test_tier_policy_bridge.cpython-314-pytest-9.0.2.pyc;test_ti |
| `app/routers/auth.py` | `POST /auth/login` | `auth_login` | test_api_key_provisioning.cpython-314-pytest-9.0.2.pyc;test_ |
| `app/routers/api_v1_admin/config_state.py` | `GET /config-state` | `get_config_state` | test_config_export.cpython-314-pytest-9.0.2.pyc;test_config_ |
| `app/routers/api_v1_admin/models.py` | `GET /embedding-models` | `admin_embedding_models` | test_config_export.cpython-314-pytest-9.0.2.pyc;test_config_ |
| `app/routers/api_v1_admin/models.py` | `POST /embedding-models/download` | `download_embedding_model` | test_config_export.cpython-314-pytest-9.0.2.pyc;test_config_ |
| `app/routers/api_v1_admin/skills.py` | `POST /file-sync` | `admin_file_sync` | test_config_export.cpython-314-pytest-9.0.2.pyc;test_config_ |
| `app/routers/chat/_routes.py` | `POST /chat/check-secrets` | `check_secrets` | test_secret_redaction_integration.cpython-314-pytest-9.0.2.p |

**Medium-tier route gaps (not listed)**: 60 GET endpoints with no exercising test.

## Methodology Notes

- Public-symbol filter ran `grep -rE "from app.services.<mod> import"` over `app/` + `integrations/`; symbols never imported outside their own module are excluded (treated as private).
- Route path matching uses the router's `APIRouter(prefix=...)` concatenated with the decorator path, falling back to the decorator path alone. Path-parameter placeholders (`{id}`) are not expanded; the prefix up to the first `{` is searched literally. Short prefixes (<6 chars) are skipped, which may under-count coverage for a handful of root-level routes.
- "real" classification requires `db_session`/`async_session`/`test_db` fixture OR `AsyncClient`/`ASGITransport`/`TestClient`. Files that combine mocks with a real fixture are counted as real — the real path dominates.
- E2E tests under `tests/e2e/` are NOT counted here; per `CLAUDE.md`, the e2e suite runs on the test server and covers multi-process scenarios rather than per-function contracts.
- Risk heuristic is lexical (function name), not semantic. A function named `resolve_providers` is tagged "high" (read), `persist_provider_config` "critical" (mutate) — re-check judgement calls before prioritizing work.
