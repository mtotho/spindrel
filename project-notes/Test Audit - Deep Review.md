---
tags: [testing, audit]
status: reference
updated: 2026-04-17
---

# Test Audit — Deep Review (Top-5 E.13 Offenders)

File-level review of the five worst unit-test files flagged by the shallow inventory (E.13 hits). Each section reports the 10 worst violations by severity, shows a single before/after refactor against the dominant problem, estimates effort, and flags production-code blockers that make the rewrite non-mechanical.

Rule numbers follow `~/personal/dotfiles/claude/skills/testing-python/SKILL.md`. The rewrite target uses the existing `db_session` fixture at `/home/mtoth/personal/agent-server/tests/integration/conftest.py` (real SQLite-in-memory, already wired for JSONB/UUID/TSVECTOR compilers).

There is no `tests/factories/` package today — new factory modules are a cross-file prerequisite. See the final section.

---

## 1) tests/unit/test_multi_bot_channels.py — 2169 LOC

Dominant pattern: `AsyncMock()` sessions with hand-rolled `scalars.return_value.all.return_value = [...]` chains plus chained `patch()` of internal symbols (`app.db.engine.async_session`, `app.agent.bots.get_bot`, `app.agent.loop.run_stream`, `app.services.sessions._resolve_workspace_base_prompt_enabled`, …).

### Top 10 violations

**Critical**

- `tests/unit/test_multi_bot_channels.py:43-49` — [E.13] — `_mock_db_with_member_rows()` returns an `AsyncMock()` with `scalars.return_value.all.return_value = rows`; 30+ tests in this file reuse it. This is the anti-pattern the skill explicitly calls out in `SKILL.md:134-140`.
- `tests/unit/test_multi_bot_channels.py:82-88` — [E.13] — `test_tag_matches_member_bot` drives `_maybe_route_to_member_bot` against a mocked DB + a `MagicMock()` channel; the routing SQL is never exercised.
- `tests/unit/test_multi_bot_channels.py:302-309` — [E.1] — `test_delegation_adds_bot_to_set` stacks six internal patches (`app.services.delegation.settings`, `app.agent.bots.get_bot`, `app.agent.loop.run_stream`, `app.services.sessions._effective_system_prompt`, `app.agent.persona.get_persona`, `app.agent.context.snapshot_agent_context`). At this point nothing real is being tested.
- `tests/unit/test_multi_bot_channels.py:579-586` — [E.1] — `test_snapshot_strips_primary_system_messages` patches `app.db.engine.async_session`, `app.agent.loop.run_stream`, `app.services.channel_events.publish_typed`, `app.services.sessions.persist_turn`, `app.agent.context.set_agent_context`, `app.routers.chat._multibot._record_channel_run`, and `app.services.sessions._resolve_workspace_base_prompt_enabled` in one context. Seven internal patches for one assertion.
- `tests/unit/test_multi_bot_channels.py:358-369` — [B.3] — `test_member_bot_ids_merged_into_delegate_index` asserts `== ["delegate-a", "tagged-b", "member-c"]` against a list *the test itself built three lines earlier*. It's testing `dict.fromkeys`, not product code.
- `tests/unit/test_multi_bot_channels.py:371-392` — [B.23] — `test_awareness_message_format` reconstructs the awareness-message formatting inline and then asserts on the string it just assembled. Zero production code runs.
- `tests/unit/test_multi_bot_channels.py:426-456` — [B.23] — `test_awareness_identifies_current_bot` re-implements the whole preamble builder inline, then asserts on its own output. Any future change to the real builder will pass this test.

**High**

- `tests/unit/test_multi_bot_channels.py:742-755` — [M.11] — `test_flush_db_error_handled_gracefully` calls `_flush_member_bots` and relies on "no exception" as the pass condition with no assertion. Should be `pytest.raises` if it's expected to raise, or an observable side-effect assertion if it shouldn't.
- `tests/unit/test_multi_bot_channels.py:982-990` — [D.11] — `test_no_tags_in_response_does_nothing`: comment reads "No error = success (nothing to assert, just verifying no crash)." No assertion at all.

**Cosmetic**

- `tests/unit/test_multi_bot_channels.py:54, 63, 74, 93, 110, 126, …` — [A.1] — Class-nested method titles use `test_<short_phrase>` instead of `test_when_<scenario>_then_<expectation>` (e.g. `test_tag_matches_member_bot` → `test_when_mention_matches_channel_member_then_routes_to_member`).

### Refactor example

**Current** (`tests/unit/test_multi_bot_channels.py:73-90`):

```
 73  @pytest.mark.asyncio
 74  async def test_tag_matches_member_bot(self):
 75      from app.routers.chat import _maybe_route_to_member_bot
 76
 77      primary = _make_bot(id="primary-bot")
 78      member = _make_bot(id="helper", name="Helper Bot")
 79      channel = MagicMock()
 80      channel.id = uuid.uuid4()
 81
 82      db = _mock_db_with_member_rows([_make_member_row("helper")])
 83
 84      with patch("app.agent.bots.get_bot", return_value=member):
 85          result_bot, result_cfg = await _maybe_route_to_member_bot(
 86              db, channel, primary, "@helper what do you think?"
 87          )
 88
 89      assert result_bot.id == "helper"
 90      assert result_cfg == {}
```

**Rewrite** (real DB + factory):

```python
# tests/factories/multibot.py  (new)
def build_channel_bot_member(**overrides) -> ChannelBotMember:
    defaults = dict(
        id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        bot_id=f"bot-{uuid.uuid4().hex[:6]}",
        config={},
    )
    return ChannelBotMember(**{**defaults, **overrides})

# tests/unit/test_multi_bot_channels.py
async def test_when_mention_matches_channel_member_then_routes_to_member(db_session):
    primary = await db_session.merge(build_bot(id="primary-bot"))
    helper  = await db_session.merge(build_bot(id="helper", name="Helper Bot"))
    channel = await db_session.merge(build_channel(bot_id=primary.id))
    await db_session.merge(build_channel_bot_member(channel_id=channel.id, bot_id=helper.id))
    await db_session.commit()

    routed_bot, cfg = await _maybe_route_to_member_bot(
        db_session, channel, primary, "@helper what do you think?"
    )

    assert routed_bot.id == helper.id
    assert cfg == {}
```

### Effort

~55 tests, ~10 min each = **9-11 hours**. Half the tests (the Context-Injection + Multi-Bot-Identity classes) are re-implementations of production logic inline — they should be **deleted, not rewritten**, and replaced with 3-4 behavioral tests that exercise the real `context_assembly.py` path.

### Blockers

- `app.agent.bots.get_bot` is a module-level registry lookup (`_registry` dict). Tests that need to add a bot must either seed the `Bot` DB row **and** patch the in-memory registry (the existing `client` fixture already does this via `patch("app.agent.bots._registry", _TEST_REGISTRY)`), or the `db_session` fixture needs a helper that does both atomically.
- `current_turn_responded_bots` is a `ContextVar` — tests in `TestAntiLoop` set it without teardown. Add a `contextvar_isolation` fixture that snapshots/restores or the next test in the same worker inherits state (B.28 hazard).
- `_run_member_bot_reply` opens its own session via `async_session()` rather than accepting a session parameter. The `client` fixture already patches `app.services.workflows.async_session`; extend that pattern to `app.routers.chat._multibot.async_session`. No code change required.

---

## 2) tests/unit/test_manage_bot_skill.py — 2070 LOC

Dominant pattern: `_mock_session(db)` helper wraps an `AsyncMock()` in a fake async-context-manager; every test then patches `app.db.engine.async_session`, `app.tools.local.bot_skills.current_bot_id`, `_embed_skill_safe`, `_check_count_warning`, and `_invalidate_cache` together.

### Top 10 violations

**Critical**

- `tests/unit/test_manage_bot_skill.py:58-66` — [E.13] — `_mock_session()` helper is the gateway: every CRUD test (~45 of them) routes through it and never touches a real session.
- `tests/unit/test_manage_bot_skill.py:159-181` — [E.13, E.1] — `test_success` patches five internal symbols and then asserts `db.add.assert_called_once()` — a textbook implementation-detail assertion (B.23) layered on a mocked session.
- `tests/unit/test_manage_bot_skill.py:183-210` — [B.23] — `test_create_populates_description_triggers_category` reaches into `db.add.call_args[0][0]` to inspect the ORM row *before* it's flushed. The assertion doesn't verify any of the DB-level default/constraint behavior the bug fix claimed to fix.
- `tests/unit/test_manage_bot_skill.py:237-252` — [E.13] — `test_duplicate_rejected` mocks `db.get` to return `existing`. With a real session, `IntegrityError` on unique constraint would surface — currently the test would pass even if the uniqueness check were removed from production code.
- `tests/unit/test_manage_bot_skill.py:290-299` — [E.13] — `test_empty` drives `list_bot_skills` with `db.execute = AsyncMock(side_effect=[count_result, rows_result])`. This couples the test to the order of `execute()` calls inside the function — any refactor (say, merging count + rows into one query) fails this test without a behavior change.

**High**

- `tests/unit/test_manage_bot_skill.py:264-285` — [A.13] — `test_count_warning_included` chains six nested `patch()` calls as context managers (`with (patch(...), patch(...), …):`), pushing the statement count well above the 10-statement max (A.3).
- `tests/unit/test_manage_bot_skill.py:37-51` — [B.23] — `_make_skill_row()` builds a MagicMock with fixed attributes; tests then assert on those same attributes. The factory can't catch schema drift because it isn't the real model.

**Cosmetic**

- `tests/unit/test_manage_bot_skill.py:74, 77, 80, 83, 91, 95, 104, 112, …` — [A.1] — titles read `test_bot_skill_id_basic`, `test_slugify_strips_special_chars`. Rename to `test_when_<input>_then_<output>` form.
- `tests/unit/test_manage_bot_skill.py:104-118` — [A.10] — `test_build_content_full` has 5 assertions against a single `result` string; consolidate into one `in`-check list or one full-string equality.

### Refactor example

**Current** (`tests/unit/test_manage_bot_skill.py:237-252`):

```
237  @pytest.mark.asyncio
238  async def test_duplicate_rejected(self):
239      existing = _make_skill_row("bots/testbot/my-skill")
240      db = AsyncMock()
241      db.get = AsyncMock(return_value=existing)
242
243      with (
244          patch("app.tools.local.bot_skills.current_bot_id") as ctx,
245          patch("app.db.engine.async_session", _mock_session(db)),
246      ):
247          ctx.get.return_value = "testbot"
248          result = _parse(await manage_bot_skill(
249              action="create", name="my-skill", title="My Skill",
250              content="x" * CONTENT_MIN_LENGTH,
251          ))
252          assert "already exists" in result["error"]
```

**Rewrite**:

```python
async def test_when_skill_already_exists_then_create_rejects_with_error(
    db_session, session_factory_patch, bot_context
):
    await db_session.merge(build_bot_skill(
        id="bots/testbot/my-skill", name="My Skill",
    ))
    await db_session.commit()

    result = json.loads(await manage_bot_skill(
        action="create",
        name="my-skill",
        title="My Skill",
        content="x" * CONTENT_MIN_LENGTH,
    ))

    assert "already exists" in result["error"]
```

Where `session_factory_patch` and `bot_context` are shared fixtures (see Cross-file Patterns) that (a) point `app.db.engine.async_session` at the test engine and (b) set `current_bot_id` to `"testbot"`.

### Effort

~60 tests, ~8-12 min each = **10-12 hours**. The helper functions (`_bot_skill_id`, `_slugify`, `_extract_body`, `_build_content`) are pure functions — those ~15 tests already pass the skill rules modulo A.1 titles and need no rewrite, only renames (~30 min).

### Blockers

- `manage_bot_skill` opens its own `async with async_session() as db:` block (~10 places in `bot_skills.py`). Tests must patch `app.db.engine.async_session` globally per test — this is a shared-fixture problem, not a per-test one.
- `_embed_skill_safe` calls out to the embedding provider. Keep it patched (legitimate external dep per E.1) but via a dedicated fixture, not per-test inline.
- `current_bot_id` is a `ContextVar`; same teardown concern as test_multi_bot_channels — use a `bot_context` fixture that sets/resets per test.
- `_invalidate_cache` is module-level state. The fixture should reset the cache in teardown (B.28) — currently, leakage between tests is invisible because the mocked DB obscures it.

---

## 3) tests/unit/test_task_tools.py — 440 LOC

Smallest of the five. Dominant pattern: every test builds `task = MagicMock()` with 15-20 `task.field = value` lines, then patches `async_session` and the five `current_*` ContextVars.

### Top 10 violations

**Critical**

- `tests/unit/test_task_tools.py:69-73` — [E.13] — `_mock_async_session` method is the local version of the same pattern. `TestCreateTask`, `TestListTasks`, `TestUpdateTask` all use it.
- `tests/unit/test_task_tools.py:116-139` — [C.3, E.13] — `test_detail_mode` hand-constructs a 24-field `MagicMock` for a `Task` row, then asserts on four of the 24 fields. 19 fields of noise per test.
- `tests/unit/test_task_tools.py:85-103` — [E.1] — `test_basic_create` patches six internal ContextVars (`current_bot_id`, `current_session_id`, `current_channel_id`, `current_client_id`, `current_dispatch_type`, `current_dispatch_config`) in one stacked `with`. The real code under test (`schedule_task`) does 80 lines of work on a mocked DB; nothing real is exercised.
- `tests/unit/test_task_tools.py:186-197` — [E.13] — `test_detail_mode_with_template` uses `db.get = AsyncMock(side_effect=lambda model, id: task if id == task_id else tpl)` — testing the test helper's dispatch, not the real multi-model `db.get` lookup.
- `tests/unit/test_task_tools.py:410-440` — [B.23] — `TestHeartbeatPatchNull` class: the test comment says "Replicate the fixed loop logic inline" and then asserts against the inlined copy. This is not a test — it's a re-implementation of production code that validates itself.

**High**

- `tests/unit/test_task_tools.py:150-153` — [D.13] — `test_detail_mode` has 4 equality assertions against 4 separate fields of `data`; collapse to a dict-subset equality.
- `tests/unit/test_task_tools.py:237-238` — [B.3, D.11] — `assert "No" in result and "tasks" in result` — weak string-containment on two magic tokens, neither defined in Arrange.

**Cosmetic**

- `tests/unit/test_task_tools.py:16, 32, 52, 76, 113, 156, …` — [A.1] — titles throughout use short verb phrases instead of `test_when_<scenario>_then_<expectation>`.

### Refactor example

**Current** (`tests/unit/test_task_tools.py:75-103`):

```
 75  @pytest.mark.asyncio
 76  async def test_basic_create(self):
 77      from app.tools.local.tasks import schedule_task as create_task
 78
 79      db = AsyncMock()
 80      db.add = MagicMock()
 81      db.commit = AsyncMock()
 82      db.refresh = AsyncMock()
 83      cm = self._mock_async_session(db)
 84
 85      with patch("app.tools.local.tasks.async_session", return_value=cm), \
 86           patch("app.tools.local.tasks.current_bot_id") as mock_bot, \
 87           patch("app.tools.local.tasks.current_session_id") as mock_sid, \
 88           patch("app.tools.local.tasks.current_channel_id") as mock_cid, \
 89           patch("app.tools.local.tasks.current_client_id") as mock_client, \
 90           patch("app.tools.local.tasks.current_dispatch_type") as mock_dtype, \
 91           patch("app.tools.local.tasks.current_dispatch_config") as mock_dcfg:
 92          mock_bot.get.return_value = "test_bot"
 93          mock_sid.get.return_value = uuid.uuid4()
 94          mock_cid.get.return_value = uuid.uuid4()
 95          mock_client.get.return_value = "client1"
 96          mock_dtype.get.return_value = "none"
 97          mock_dcfg.get.return_value = {}
 98
 99          result = await create_task(prompt="do something")
100          data = json.loads(result)
101          assert data["status"] == "pending"
102          assert data["task_type"] == "scheduled"
103          assert data["bot_id"] == "test_bot"
104      
```

**Rewrite**:

```python
async def test_when_scheduling_task_with_bot_context_then_creates_pending_scheduled_task(
    db_session, tasks_session_factory_patch, agent_context
):
    agent_context(bot_id="test_bot", session_id=uuid.uuid4(), channel_id=uuid.uuid4())

    result = json.loads(await schedule_task(prompt="do something"))

    assert {k: result[k] for k in ["status", "task_type", "bot_id"]} == {
        "status": "pending",
        "task_type": "scheduled",
        "bot_id": "test_bot",
    }
    # Extra Mile: verify a Task row was actually persisted
    row = (await db_session.execute(select(Task).where(Task.id == result["id"]))).scalar_one()
    assert row.bot_id == "test_bot"
```

Where `agent_context` is a fixture that sets all five ContextVars in one call and tears them down.

### Effort

~25 tests total, but `TestHeartbeatPatchNull` (4 tests at lines 410-440) should be **deleted** — they test a copy of production code pasted into the test. Remaining ~21 tests, ~8 min each = **3-4 hours**.

### Blockers

- `app.tools.local.tasks` imports `async_session` at module top (line 20) — patching needs to target the local re-bound name, not `app.db.engine.async_session`. Test-side doable; no production refactor required.
- The five `current_*` ContextVars are imported into `tasks.py` at module top (lines 10-15) as direct symbol bindings. Tests must patch the **names inside `tasks.py`**, not the source in `app.agent.context`. A shared `agent_context` fixture should set the real ContextVar (one place) and let the import alias resolve naturally — this is a test-infrastructure fix worth making once.
- `_resolve_bot_channel` (line 193) does `await db.get(Bot, bot_id)`. Tests using real DB need to seed a `Bot` row or the function 404s. Factory needed.

---

## 4) tests/unit/test_workflow_advancement.py — 1652 LOC

Dominant pattern: `_make_task`/`_make_workflow_run`/`_make_workflow` helpers return `MagicMock()` (not real ORM rows), tests drive `on_step_task_completed` with `mock_db.get = AsyncMock(side_effect=mock_get)` where `mock_get` dispatches on `model.__name__`.

### Top 10 violations

**Critical**

- `tests/unit/test_workflow_advancement.py:15-68` — [C.3, E.13] — `_make_task` / `_make_workflow_run` / `_make_workflow` return MagicMocks. A real `WorkflowRun.step_states` is a JSONB column — bugs in that serialization layer cannot be caught with mocks.
- `tests/unit/test_workflow_advancement.py:185-211` — [E.13, E.1] — `test_uses_fresh_task_result_not_stale` mocks `async_session`, `advance_workflow`, `_dispatch_workflow_event` and uses a handwritten `mock_get` dispatcher on `model.__name__`. The bug this test was written for (stale vs fresh `task.result`) can only be verified if the **DB round-trip** is real, because "stale" is defined by the ORM's identity map vs a fresh `session.get`.
- `tests/unit/test_workflow_advancement.py:200-204` — [B.3] — `committed_states` captures `run.step_states` in a `mock_commit` side effect. The "commit" never actually writes anything — `mock_commit` is a lambda that appends the in-memory dict the test already owns. Smoking-gun failure: the assertion proves the test, not the code.
- `tests/unit/test_workflow_advancement.py:266-298` — [E.13] — `test_skips_cancelled_run` asserts `mock_advance.assert_not_called()` on a mocked `advance_workflow`. If someone renames the function or moves the guard elsewhere, this test stays green.
- `tests/unit/test_workflow_advancement.py:38-42` — [B.5] — factory returns a `step_states` structure with 8 keys; the tests only read `status`, `task_id`, `result`, `error`. The extra four keys (started_at, completed_at, correlation_id, …) are noise that shadows the real schema.

**High**

- `tests/unit/test_workflow_advancement.py:195-204` — [A.13] — `async def mock_commit(): committed_states.append([dict(s) for s in run.step_states])` — nested function + list comp inside the Act setup. Move to an Arrange-phase spy or, better, drop the mock and read from the real DB after.
- `tests/unit/test_workflow_advancement.py:185-191` — [A.13] — `async def mock_get(model, id_, **kwargs): if name == "WorkflowRun": … if name == "Workflow": … if name == "Task" and id_ == task_id: …` — a three-branch dispatch function inside a test. Replace with real rows in `db_session`.

**Cosmetic**

- `tests/unit/test_workflow_advancement.py:82, 100, 114, 136, 161, 219, 269, …` — [A.1] — class-nested test names use verb phrases.
- `tests/unit/test_workflow_advancement.py:214` — [D.11] — `assert committed_states, "No commit was made"` followed by `assert step_0["status"] == "done"` and `assert step_0["result"] == "…"` — three assertions where the first is redundant (the second/third IndexError would already signal "no commit").

### Refactor example

**Current** (`tests/unit/test_workflow_advancement.py:161-217`):

```
161  @pytest.mark.asyncio
162  async def test_uses_fresh_task_result_not_stale(self):
163      from app.services.workflow_executor import on_step_task_completed
164  
165      run_id = uuid.uuid4()
166      task_id = uuid.uuid4()
167  
168      stale_task = _make_task(id=task_id, result=None, correlation_id=None)
169      fresh_task = _make_task(id=task_id, result="Step 0 completed successfully", correlation_id=uuid.uuid4())
170  
171      run = _make_workflow_run(id=run_id, step_count=2)
172      run.step_states[0]["status"] = "running"
173      run.step_states[0]["task_id"] = str(task_id)
174  
175      workflow = _make_workflow()
176      committed_states = []
177  
178      async def mock_get(model, id_, **kwargs):
179          name = model.__name__ if hasattr(model, "__name__") else str(model)
180          if name == "WorkflowRun": return run
181          if name == "Workflow":    return workflow
182          if name == "Task" and id_ == task_id: return fresh_task
183          return None
184      
185      mock_db = AsyncMock()
186      mock_db.__aenter__ = AsyncMock(return_value=mock_db)
187      mock_db.__aexit__  = AsyncMock(return_value=False)
188      mock_db.get = AsyncMock(side_effect=mock_get)
189  
190      async def mock_commit():
191          committed_states.append([dict(s) for s in run.step_states])
192      mock_db.commit = AsyncMock(side_effect=mock_commit)
193  
194      with (
195          patch("app.services.workflow_executor.async_session", return_value=mock_db),
196          patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock),
197          patch("app.services.workflow_executor._dispatch_workflow_event", new_callable=AsyncMock),
198      ):
199          await on_step_task_completed(str(run_id), 0, "complete", stale_task)
200  
201      assert committed_states, "No commit was made"
202      step_0 = committed_states[0][0]
203      assert step_0["status"] == "done"
204      assert step_0["result"] == "Step 0 completed successfully"
```

**Rewrite**:

```python
async def test_when_step_task_completes_then_step_state_uses_fresh_db_result(
    db_session, workflow_executor_session_patch
):
    # Arrange — real rows, real JSONB round-trip
    run = await db_session.merge(build_workflow_run(
        step_states=[{"status": "running", "task_id": None, "result": None}],
    ))
    workflow = await db_session.merge(build_workflow(id=run.workflow_id))
    task = await db_session.merge(build_task(
        id=run.step_states[0]["task_id"] or uuid.uuid4(),
        result="Step 0 completed successfully",
    ))
    run.step_states[0]["task_id"] = str(task.id)
    flag_modified(run, "step_states")
    await db_session.commit()
    stale_task = build_task(id=task.id, result=None)  # simulates caller's stale view

    # Act
    with patch("app.services.workflow_executor.advance_workflow", new_callable=AsyncMock):
        await on_step_task_completed(str(run.id), 0, "complete", stale_task)

    # Assert — read the real row back
    await db_session.refresh(run)
    assert run.step_states[0] == {
        "status": "done",
        "task_id": str(task.id),
        "result": task.result,
        "error": None,
        # Factory fills the rest with None defaults; real row preserves them
        **{k: None for k in ["started_at", "completed_at", "correlation_id"]},
    }
```

### Effort

~50 tests, ~12-15 min each = **10-12 hours**. Workflow tests often need multi-row setup (run + workflow + tasks + steps), so factory work is load-bearing.

### Blockers

- `workflow_executor.py` opens its own `async_session()` at ~15 call sites. `conftest.py` already patches `app.services.workflow_executor.async_session` for the `client` fixture — add a non-HTTP variant (`workflow_executor_session_patch`) that reuses that factory for direct function tests.
- `on_step_task_completed` calls `advance_workflow` at the end (line 1010). For step-completion unit tests, patching it (legitimate seam between "step done" and "pick next step") is fine; for full-pipeline tests, let it run against the real DB.
- `step_states` is JSONB with mutation tracking — tests **must** call `flag_modified(run, "step_states")` after dict mutation or SQLAlchemy won't persist. The CLAUDE.md project rule mentions this explicitly. Factories should set `step_states` via constructor, not post-hoc assignment.
- `WorkflowRun.workflow_snapshot` is a nullable JSONB column that the production code sometimes relies on instead of `workflow_id`. Tests need to decide which path is under test per case — this isn't a mock-to-real mechanical swap, it's a code-reading exercise.

---

## 5) tests/unit/test_memory_hygiene.py — 1401 LOC

Dominant pattern: `_make_bot` / `_make_bot_row` helpers return `MagicMock()`; tests stack `patch("app.services.memory_hygiene.settings")` + a mocked `async_session` context manager + mocked `db.execute(side_effect=[a, b, c, d])` to simulate sequential queries.

### Top 10 violations

**Critical**

- `tests/unit/test_memory_hygiene.py:203-223` — [E.13] — `_mock_db_session` does `db.execute = AsyncMock(side_effect=[bots_result, count_result])`. The test is now bound to query call-order inside `check_memory_hygiene`; any refactor breaks it.
- `tests/unit/test_memory_hygiene.py:15-19, 56-59, 77-81, 98-101, 177-201` — [C.3, E.13] — five different `_make_bot` helpers across five classes, all returning `MagicMock()` instead of a real `Bot` row. Schema drift won't be caught.
- `tests/unit/test_memory_hygiene.py:140-159` — [E.13] — `test_creates_task_with_correct_fields` creates `bot_row = MagicMock()` and asserts `db.add.call_args[0][0].bot_id == "test-bot"`. A real `Task` model would enforce NOT NULL on `channel_id` (it's nullable per the assertion on line 156 — good! — but we can't verify that *without a real DB*).
- `tests/unit/test_memory_hygiene.py:325-365` — [E.13, A.13] — `test_activity_check_skips_no_activity` sets `db.execute = AsyncMock(side_effect=[bots_result, activity_result])` — second branch-test bound to call-order. Plus 15 statements in the Arrange phase (violates A.3).
- `tests/unit/test_memory_hygiene.py:405-427` — [B.23] — `test_query_includes_member_channels` compiles the SQLAlchemy statement passed to `db.execute` and string-matches `"channel_bot_members"` and `"OR"` in the SQL. This is the canonical anti-pattern from `sqlalchemy-real-db.md:155` ("❌ Asserting on the SQL string"). Replace with: real data + member channel + assert the returned count differs between the primary-only and member-channel cases.

**High**

- `tests/unit/test_memory_hygiene.py:32-52` — [E.1] — `patch("app.services.memory_hygiene.settings")` stubs settings per test. Better: a session-scoped `test_settings` fixture that sets `MEMORY_HYGIENE_*` via env vars and lets the real config load (exercises config.py too).
- `tests/unit/test_memory_hygiene.py:388-402` — [D.11] — two tests each with a single bool assertion. `_has_activity_since` returning True/False is exactly what `@pytest.mark.parametrize` is for (one test, two cases).

**Cosmetic**

- `tests/unit/test_memory_hygiene.py:22, 27, 32, 41, 48, 62, 69, 83, 92, 103, 113, 120, …` — [A.1] — every test title is a short declarative phrase; none use the `when_X_then_Y` template.

### Refactor example

**Current** (`tests/unit/test_memory_hygiene.py:131-159`):

```
131  class TestCreateHygieneTask:
132      @pytest.mark.asyncio
133      async def test_creates_task_with_correct_fields(self):
134          from app.services.memory_hygiene import create_hygiene_task
135  
136          bot_row = MagicMock()
137          bot_row.id = "test-bot"
138          bot_row.memory_hygiene_prompt = None
139          bot_row.memory_scheme = "workspace-files"
140  
141          db = AsyncMock()
142          db.get = AsyncMock(return_value=bot_row)
143          db.add = MagicMock()
144          db.commit = AsyncMock()
145  
146          with patch("app.services.memory_hygiene.settings") as mock_settings:
147              mock_settings.MEMORY_HYGIENE_PROMPT = ""
148              task_id = await create_hygiene_task("test-bot", db)
149  
150          assert task_id is not None
151          db.add.assert_called_once()
152          task = db.add.call_args[0][0]
153          assert task.bot_id == "test-bot"
154          assert task.task_type == "memory_hygiene"
155          assert task.status == "pending"
156          assert task.channel_id is None
157          assert task.session_id is None
158          assert task.dispatch_type == "none"
159          db.commit.assert_awaited_once()
```

**Rewrite**:

```python
async def test_when_creating_hygiene_task_then_task_is_pending_with_bot_scope(
    db_session, test_settings
):
    bot = await db_session.merge(build_bot(
        id="test-bot", memory_scheme="workspace-files", memory_hygiene_prompt=None,
    ))
    await db_session.commit()

    task_id = await create_hygiene_task(bot.id, db_session)

    task = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one()
    assert (task.bot_id, task.task_type, task.status, task.channel_id, task.dispatch_type) == (
        bot.id, "memory_hygiene", "pending", None, "none"
    )
```

### Effort

~40 tests. ~15 of them (the pure `resolve_*` helpers on Bot rows) are near-compliant and just need title renames + a minimal `build_bot_row()` factory (~2 hours). The `TestCheckMemoryHygiene` class (10 tests, sequential-execute pattern) is the bulk — ~15 min each = ~2.5 hours. `test_query_includes_member_channels` should be **rewritten as a behavioral test** (insert a member channel, assert activity detected) rather than compile-string inspection. Total: **5-6 hours**.

### Blockers

- `check_memory_hygiene()` opens its own session via `async with async_session() as db:` (line 956) — same problem as bot_skills/tasks, same fix (shared fixture that patches the local alias).
- `settings` is a global `Settings()` instance from `app.config`. Tests currently patch the module attribute; cleaner is to let pydantic pick up env vars (set via `monkeypatch.setenv("MEMORY_HYGIENE_ENABLED", "true")` in a fixture). Non-blocking but yields more realistic coverage.
- `_has_activity_since` constructs a query that joins `ChannelBotMember`. To test it realistically you need: `Bot`, `Channel`, `ChannelBotMember`, and `ChatMessage` rows. ~5-line factory setup per test but the existing `conftest.py` engine already supports all these tables.
- `memory_hygiene.py:_col()` (line 96) uses `getattr(bot_row, col_name)` — works fine against real ORM rows; no blocker.

---

## Cross-file Patterns

These recur in 4 or 5 of the audited files and should become shared infrastructure before any rewrite lands. Each is a candidate for a dedicated PR ahead of per-file cleanup.

### 1. `tests/factories/` package — NEW

Currently nonexistent (`Glob "tests/factories/**"` returns zero files). Blocker for ~80% of rewrites. Required factories based on the five files:

- `build_bot()` — `Bot` ORM row (all five files inline it)
- `build_channel()` + `build_channel_bot_member()` — multi-bot routing tests
- `build_bot_skill()` — manage_bot_skill tests
- `build_task()` / `build_prompt_template()` — tasks + workflow tests
- `build_workflow()` / `build_workflow_run()` (with correct JSONB `step_states` defaults + `flag_modified`) — workflow tests
- `build_bot_row()` with all `memory_hygiene_*` / `skill_review_*` columns — hygiene tests

Scaffold under `tests/factories/` with `faker` for unique fields. This alone removes ~30% of the statement count from the target files.

### 2. Session-factory patch fixtures

Four of the five modules under test (`bot_skills`, `tasks`, `workflow_executor`, `memory_hygiene`, plus `chat._multibot`) open their own `async with async_session()` blocks. Every current test patches this inline. Ship one fixture per module in `tests/conftest.py` (or a shared `tests/unit/conftest.py`):

```python
@pytest_asyncio.fixture
async def patched_async_sessions(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with (
        patch("app.tools.local.bot_skills.async_session", factory),
        patch("app.tools.local.tasks.async_session", factory),
        patch("app.services.workflow_executor.async_session", factory),
        patch("app.services.memory_hygiene.async_session", factory),
        patch("app.routers.chat._multibot.async_session", factory),
        patch("app.db.engine.async_session", factory),
    ):
        yield factory
```

The integration `client` fixture already does this selectively (lines 233-235 of `tests/integration/conftest.py`); unit tests need the same without the HTTP client.

### 3. `agent_context` fixture for the six ContextVars

`current_bot_id`, `current_session_id`, `current_channel_id`, `current_client_id`, `current_dispatch_type`, `current_dispatch_config`, `current_correlation_id`, `current_turn_responded_bots` are all ContextVars set inline in 50+ tests with no teardown (B.28 hazard). One fixture that snapshots tokens on enter and `reset()`s them on exit eliminates hundreds of lines of setup.

### 4. Inline re-implementation of production logic

Spotted in `test_multi_bot_channels.py:358-456` and `test_task_tools.py:410-440`. These tests copy a block of production code into the test and then assert the copy behaves as intended. Delete these outright — they cannot catch bugs. Replace with one integration-level test per feature that exercises the real code path (~2 net tests, not ~10).

### 5. `patch("…settings")` pattern

All five files use `patch("app.X.settings") as mock_settings; mock_settings.FOO = bar`. Prefer `monkeypatch.setenv("FOO", "bar")` + `importlib.reload(app.config)` OR a session-scoped `test_settings` fixture that writes to a Pydantic model instance directly. This also exercises `app/config.py` parsing (currently zero tests do).

### 6. Mocked DB-execute call-order coupling

`db.execute = AsyncMock(side_effect=[result_a, result_b])` in tests ties the test to the *order* of SELECTs in production code. Every refactor that combines, reorders, or adds a query breaks these tests without any behavior change. Real DB + real queries have no such coupling — it's the single highest-leverage reason to adopt the `db_session` fixture.

---

## Totals

| File | Tests | Est. hours | Biggest blocker |
|---|---|---|---|
| test_multi_bot_channels.py | ~55 (delete ~15) | 9-11 | Re-implementation tests that can't be fixed, only deleted |
| test_manage_bot_skill.py | ~60 | 10-12 | Six+ internal patches per test; needs `patched_async_sessions` + `bot_context` fixtures first |
| test_task_tools.py | ~25 (delete 4) | 3-4 | ContextVar alias imports into `tasks.py` |
| test_workflow_advancement.py | ~50 | 10-12 | JSONB `step_states` + `flag_modified`; multi-row seed complexity |
| test_memory_hygiene.py | ~40 | 5-6 | Sequential-execute call-order coupling; one SQL-string test to delete |
| **Total** | **~230** | **37-45 hours** | Shared factories + fixtures are prerequisite |

Prerequisite shared infrastructure (factories + fixtures): **~6-8 hours**, ships before any per-file cleanup. After that, per-file work is mechanical. Realistic single-developer wall time for the full top-5 cleanup: **1.5-2 focused weeks**.
