from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_compaction_runs_use_tight_chat_chrome() -> None:
    source = (REPO_ROOT / "ui/src/components/chat/OrderedTranscript.tsx").read_text()

    assert 'envelope?.view_key === "compaction_run"' in source
    assert 'className={`rounded-lg border overflow-hidden' in source


def test_compaction_summary_starts_collapsed_and_recovers_after_completion() -> None:
    source = (REPO_ROOT / "ui/src/components/chat/RichToolResult.tsx").read_text()

    assert "const [expanded, setExpanded] = useState(false)" in source
    assert 'payload.status === "completed"' in source
    assert 'setExpanded(false)' in source
    assert "Hide summary" in source
    assert "Show summary" in source
