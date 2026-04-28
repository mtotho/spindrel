from app.agent.loop_state import LoopDispatchState, LoopRunState


def test_loop_dispatch_state_alias_keeps_old_import_path_compatible():
    state = LoopDispatchState(messages=[])

    assert isinstance(state, LoopRunState)
    assert state.messages == []


def test_append_thinking_accumulates_with_section_breaks():
    state = LoopRunState(messages=[])

    state.append_thinking("first")
    state.append_thinking("")
    state.append_thinking("second")

    assert state.thinking_content == "first\n\nsecond"
