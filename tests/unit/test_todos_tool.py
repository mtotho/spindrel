"""Unit tests for app.tools.local.todos tool functions."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from app.db.models import Todo

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_todo(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        bot_id="test-bot",
        channel_id=uuid.uuid4(),
        content="Test todo",
        status="pending",
        priority=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return Todo(**defaults)


class FakeSession:
    """Minimal async-context-manager DB session stub."""

    def __init__(self, todos=None, get_result=None):
        self._todos = todos or []
        self._get_result = get_result
        self._added = []
        self._deleted = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    def add(self, obj):
        self._added.append(obj)

    async def commit(self):
        pass

    async def refresh(self, obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = uuid.uuid4()

    async def get(self, model, pk):
        return self._get_result

    async def delete(self, obj):
        self._deleted.append(obj)

    async def execute(self, stmt):
        return FakeResult(self._todos)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


def _patch_context(bot_id="test-bot", channel_id=None):
    """Return a context manager that patches bot_id and channel_id."""
    if channel_id is None:
        channel_id = uuid.uuid4()
    return (
        patch("app.tools.local.todos.current_bot_id", MagicMock(get=MagicMock(return_value=bot_id))),
        patch("app.tools.local.todos.current_channel_id", MagicMock(get=MagicMock(return_value=channel_id))),
    )


# ---------------------------------------------------------------------------
# create_todo
# ---------------------------------------------------------------------------

class TestCreateTodo:
    async def test_create_todo(self):
        from app.tools.local.todos import create_todo

        session = FakeSession()
        p_bot, p_ch = _patch_context()
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await create_todo(content="Buy milk")

        data = json.loads(result)
        assert data["content"] == "Buy milk"
        assert data["status"] == "pending"
        assert "id" in data

    async def test_create_todo_with_priority(self):
        from app.tools.local.todos import create_todo

        session = FakeSession()
        p_bot, p_ch = _patch_context()
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await create_todo(content="Urgent task", priority=5)

        assert len(session._added) == 1
        assert session._added[0].priority == 5

    async def test_create_todo_priority_as_string(self):
        """LLM tool runner may pass priority as a string; verify coercion to int."""
        from app.tools.local.todos import create_todo

        session = FakeSession()
        p_bot, p_ch = _patch_context()
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await create_todo(content="String priority task", priority="5")

        assert len(session._added) == 1
        assert session._added[0].priority == 5
        assert isinstance(session._added[0].priority, int)

    async def test_create_todo_empty_content(self):
        from app.tools.local.todos import create_todo

        p_bot, p_ch = _patch_context()
        with p_bot, p_ch:
            result = await create_todo(content="  ")
        assert "Error" in result

    async def test_create_todo_no_bot_id(self):
        from app.tools.local.todos import create_todo

        p_bot, p_ch = _patch_context(bot_id=None)
        with p_bot, p_ch:
            result = await create_todo(content="test")
        assert "Error" in result


# ---------------------------------------------------------------------------
# list_todos
# ---------------------------------------------------------------------------

class TestListTodos:
    async def test_list_todos_empty(self):
        from app.tools.local.todos import list_todos

        session = FakeSession(todos=[])
        p_bot, p_ch = _patch_context()
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await list_todos()

        assert result == "No todos found."

    async def test_list_todos_returns_items(self):
        from app.tools.local.todos import list_todos

        todo = _make_todo(content="Do stuff", priority=2)
        session = FakeSession(todos=[todo])
        p_bot, p_ch = _patch_context()
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await list_todos()

        assert "Do stuff" in result
        assert "p2" in result

    async def test_list_todos_no_channel(self):
        from app.tools.local.todos import list_todos

        with (
            patch("app.tools.local.todos.current_bot_id", MagicMock(get=MagicMock(return_value="test-bot"))),
            patch("app.tools.local.todos.current_channel_id", MagicMock(get=MagicMock(return_value=None))),
        ):
            result = await list_todos()
        assert "Error" in result


# ---------------------------------------------------------------------------
# complete_todo
# ---------------------------------------------------------------------------

class TestCompleteTodo:
    async def test_complete_todo(self):
        from app.tools.local.todos import complete_todo

        ch = uuid.uuid4()
        todo = _make_todo(channel_id=ch)
        session = FakeSession(get_result=todo)
        p_bot, p_ch = _patch_context(bot_id=todo.bot_id, channel_id=ch)
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await complete_todo(todo_id=str(todo.id))

        assert "marked as done" in result
        assert todo.status == "done"

    async def test_complete_todo_not_found(self):
        from app.tools.local.todos import complete_todo

        session = FakeSession(get_result=None)
        p_bot, p_ch = _patch_context()
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await complete_todo(todo_id=str(uuid.uuid4()))

        assert "not found" in result

    async def test_complete_todo_invalid_uuid(self):
        from app.tools.local.todos import complete_todo

        p_bot, p_ch = _patch_context()
        with p_bot, p_ch:
            result = await complete_todo(todo_id="not-a-uuid")
        assert "Error" in result


# ---------------------------------------------------------------------------
# update_todo
# ---------------------------------------------------------------------------

class TestUpdateTodo:
    async def test_update_content(self):
        from app.tools.local.todos import update_todo

        ch = uuid.uuid4()
        todo = _make_todo(channel_id=ch)
        session = FakeSession(get_result=todo)
        p_bot, p_ch = _patch_context(bot_id=todo.bot_id, channel_id=ch)
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await update_todo(todo_id=str(todo.id), content="Updated")

        assert "updated" in result
        assert todo.content == "Updated"

    async def test_update_priority(self):
        from app.tools.local.todos import update_todo

        ch = uuid.uuid4()
        todo = _make_todo(channel_id=ch, priority=0)
        session = FakeSession(get_result=todo)
        p_bot, p_ch = _patch_context(bot_id=todo.bot_id, channel_id=ch)
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            await update_todo(todo_id=str(todo.id), priority=3)

        assert todo.priority == 3

    async def test_update_priority_as_string(self):
        """LLM tool runner may pass priority as a string; verify coercion to int."""
        from app.tools.local.todos import update_todo

        ch = uuid.uuid4()
        todo = _make_todo(channel_id=ch, priority=0)
        session = FakeSession(get_result=todo)
        p_bot, p_ch = _patch_context(bot_id=todo.bot_id, channel_id=ch)
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            await update_todo(todo_id=str(todo.id), priority="7")

        assert todo.priority == 7
        assert isinstance(todo.priority, int)

    async def test_update_status(self):
        from app.tools.local.todos import update_todo

        ch = uuid.uuid4()
        todo = _make_todo(channel_id=ch)
        session = FakeSession(get_result=todo)
        p_bot, p_ch = _patch_context(bot_id=todo.bot_id, channel_id=ch)
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            await update_todo(todo_id=str(todo.id), status="done")

        assert todo.status == "done"

    async def test_update_not_found(self):
        from app.tools.local.todos import update_todo

        session = FakeSession(get_result=None)
        p_bot, p_ch = _patch_context()
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await update_todo(todo_id=str(uuid.uuid4()), content="x")

        assert "not found" in result


# ---------------------------------------------------------------------------
# delete_todo
# ---------------------------------------------------------------------------

class TestDeleteTodo:
    async def test_delete_todo(self):
        from app.tools.local.todos import delete_todo

        ch = uuid.uuid4()
        todo = _make_todo(channel_id=ch)
        session = FakeSession(get_result=todo)
        p_bot, p_ch = _patch_context(bot_id=todo.bot_id, channel_id=ch)
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await delete_todo(todo_id=str(todo.id))

        assert "deleted" in result
        assert todo in session._deleted

    async def test_delete_todo_not_found(self):
        from app.tools.local.todos import delete_todo

        session = FakeSession(get_result=None)
        p_bot, p_ch = _patch_context()
        with p_bot, p_ch, patch("app.tools.local.todos.async_session", return_value=session):
            result = await delete_todo(todo_id=str(uuid.uuid4()))

        assert "not found" in result

    async def test_delete_todo_invalid_uuid(self):
        from app.tools.local.todos import delete_todo

        p_bot, p_ch = _patch_context()
        with p_bot, p_ch:
            result = await delete_todo(todo_id="bad")
        assert "Error" in result
