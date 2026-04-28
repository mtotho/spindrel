from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.db.models import Message, Session
from app.services.agent_harnesses.interactions import (
    HarnessQuestionAnswer,
    answer_harness_question,
    create_harness_question,
    publish_harness_question,
)

pytestmark = pytest.mark.asyncio


async def test_answer_updates_original_question_and_hides_transport_row(db_session):
    session_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    db_session.add(Session(id=session_id, client_id="client-1", bot_id="codex"))
    await db_session.commit()

    interaction_id, _questions = await create_harness_question(
        db=db_session,
        session_id=session_id,
        channel_id=uuid.uuid4(),
        bot_id="codex",
        turn_id=turn_id,
        runtime="codex",
        tool_input={
            "title": "Harness has a question",
            "questions": [{"id": "q1", "question": "Proceed?"}],
        },
    )

    result, resolved_live = await answer_harness_question(
        db=db_session,
        session_id=session_id,
        interaction_id=interaction_id,
        answers=[
            HarnessQuestionAnswer(
                question_id="q1",
                answer="yes",
                selected_options=["Plan first"],
            ),
        ],
        notes="notes",
    )

    question_row = await db_session.get(Message, uuid.UUID(interaction_id))
    assert question_row is not None
    state = question_row.metadata_["harness_interaction"]
    assert state["status"] == "submitted"
    assert state["answers"] == [
        {
            "question_id": "q1",
            "answer": "yes",
            "selected_options": ["Plan first"],
        }
    ]

    answer_rows = (
        await db_session.execute(
            select(Message).where(
                Message.session_id == session_id,
                Message.role == "user",
            )
        )
    ).scalars().all()
    assert len(answer_rows) == 1
    assert answer_rows[0].metadata_["source"] == "harness_question"
    assert answer_rows[0].metadata_["hidden"] is True
    assert result.answer_message_id == answer_rows[0].id
    assert resolved_live is False


async def test_question_publish_uses_parent_channel_for_sub_sessions(db_session):
    parent_channel_id = uuid.uuid4()
    session_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    db_session.add(
        Session(
            id=session_id,
            client_id="client-1",
            bot_id="codex",
            parent_channel_id=parent_channel_id,
        )
    )
    await db_session.commit()

    interaction_id, _questions = await create_harness_question(
        db=db_session,
        session_id=session_id,
        channel_id=parent_channel_id,
        bot_id="codex",
        turn_id=turn_id,
        runtime="codex",
        tool_input={"questions": [{"id": "q1", "question": "Proceed?"}]},
    )

    with patch("app.services.agent_harnesses.interactions.publish_message") as publish:
        await publish_harness_question(interaction_id)

    assert publish.call_args.args[0] == parent_channel_id


async def test_question_answer_publish_uses_session_bus_for_channel_less_sessions(db_session):
    session_id = uuid.uuid4()
    turn_id = uuid.uuid4()
    db_session.add(Session(id=session_id, client_id="client-1", bot_id="codex"))
    await db_session.commit()

    interaction_id, _questions = await create_harness_question(
        db=db_session,
        session_id=session_id,
        channel_id=session_id,
        bot_id="codex",
        turn_id=turn_id,
        runtime="codex",
        tool_input={"questions": [{"id": "q1", "question": "Proceed?"}]},
    )

    with (
        patch("app.services.agent_harnesses.interactions.publish_message_updated") as updated,
        patch("app.services.agent_harnesses.interactions.publish_message") as publish,
    ):
        await answer_harness_question(
            db=db_session,
            session_id=session_id,
            interaction_id=interaction_id,
            answers=[HarnessQuestionAnswer(question_id="q1", answer="yes")],
        )

    assert updated.call_args.args[0] == session_id
    assert publish.call_args.args[0] == session_id
