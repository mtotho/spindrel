"""Unit tests for workspace write protection enforcement."""
import pytest
from unittest.mock import MagicMock

from app.services.shared_workspace import SharedWorkspaceService, SharedWorkspaceError


def _make_ws(write_protected_paths=None):
    ws = MagicMock()
    ws.write_protected_paths = write_protected_paths or []
    return ws


def _make_swb(write_access=None):
    swb = MagicMock()
    swb.write_access = write_access or []
    return swb


svc = SharedWorkspaceService()


class TestCommandHasWriteIntent:
    def test_redirect(self):
        assert svc._command_has_write_intent("echo hello > /tmp/file") is True

    def test_append_redirect(self):
        assert svc._command_has_write_intent("echo hello >> /tmp/file") is True

    def test_rm(self):
        assert svc._command_has_write_intent("rm -rf /workspace/common/skills/foo.md") is True

    def test_mv(self):
        assert svc._command_has_write_intent("mv /a /b") is True

    def test_touch(self):
        assert svc._command_has_write_intent("touch /workspace/common/skills/new.md") is True

    def test_mkdir(self):
        assert svc._command_has_write_intent("mkdir -p /workspace/common/skills/sub") is True

    def test_cp(self):
        assert svc._command_has_write_intent("cp src.md /workspace/common/skills/") is True

    def test_tee(self):
        assert svc._command_has_write_intent("echo data | tee /workspace/common/skills/file.md") is True

    def test_sed_inplace(self):
        assert svc._command_has_write_intent("sed -i 's/old/new/' /workspace/file.md") is True

    def test_pip_install(self):
        assert svc._command_has_write_intent("pip install requests") is True

    def test_cat_read_only(self):
        assert svc._command_has_write_intent("cat /workspace/common/skills/file.md") is False

    def test_ls(self):
        assert svc._command_has_write_intent("ls -la /workspace/common/skills/") is False

    def test_grep(self):
        assert svc._command_has_write_intent("grep -r pattern /workspace/") is False

    def test_echo_without_redirect(self):
        assert svc._command_has_write_intent("echo hello world") is False

    def test_find(self):
        assert svc._command_has_write_intent("find /workspace -name '*.md'") is False


class TestCheckWriteProtection:
    def test_no_protected_paths_allows_all(self):
        ws = _make_ws([])
        swb = _make_swb()
        # Should not raise
        svc._check_write_protection("bot1", ws, swb, "rm -rf /", "/workspace/bots/bot1")

    def test_blocks_write_command_in_protected_working_dir(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb()
        with pytest.raises(SharedWorkspaceError, match="Write blocked"):
            svc._check_write_protection(
                "bot1", ws, swb,
                "touch new.md",
                "/workspace/common/skills",
            )

    def test_blocks_write_to_subdir_of_protected_path(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb()
        with pytest.raises(SharedWorkspaceError, match="Write blocked"):
            svc._check_write_protection(
                "bot1", ws, swb,
                "mkdir sub",
                "/workspace/common/skills/pinned",
            )

    def test_blocks_write_command_referencing_protected_path(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb()
        with pytest.raises(SharedWorkspaceError, match="Write blocked"):
            svc._check_write_protection(
                "bot1", ws, swb,
                "cp file.md /workspace/common/skills/",
                "/workspace/bots/bot1",
            )

    def test_allows_read_command_in_protected_dir(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb()
        # Should not raise — cat is not a write command
        svc._check_write_protection(
            "bot1", ws, swb,
            "cat file.md",
            "/workspace/common/skills",
        )

    def test_allows_read_command_referencing_protected_path(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb()
        # Should not raise — ls is not a write
        svc._check_write_protection(
            "bot1", ws, swb,
            "ls /workspace/common/skills/",
            "/workspace/bots/bot1",
        )

    def test_wildcard_pattern_blocks(self):
        ws = _make_ws(["/workspace/bots/*/skills"])
        swb = _make_swb()
        with pytest.raises(SharedWorkspaceError, match="Write blocked"):
            svc._check_write_protection(
                "bot1", ws, swb,
                "touch new.md",
                "/workspace/bots/bot1/skills",
            )

    def test_bot_exemption_allows_write(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb(write_access=["/workspace/common/skills"])
        # Should not raise — bot has write access
        svc._check_write_protection(
            "bot1", ws, swb,
            "touch /workspace/common/skills/new.md",
            "/workspace/bots/bot1",
        )

    def test_bot_exemption_only_for_matching_path(self):
        ws = _make_ws(["/workspace/common/skills", "/workspace/common/prompts"])
        swb = _make_swb(write_access=["/workspace/common/skills"])
        # Should raise for prompts (not exempted)
        with pytest.raises(SharedWorkspaceError, match="Write blocked"):
            svc._check_write_protection(
                "bot1", ws, swb,
                "rm /workspace/common/prompts/base.md",
                "/workspace/bots/bot1",
            )

    def test_null_swb_still_enforces(self):
        ws = _make_ws(["/workspace/common/skills"])
        with pytest.raises(SharedWorkspaceError, match="Write blocked"):
            svc._check_write_protection(
                "unknown_bot", ws, None,
                "touch new.md",
                "/workspace/common/skills",
            )

    def test_redirect_to_protected_path(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb()
        with pytest.raises(SharedWorkspaceError, match="Write blocked"):
            svc._check_write_protection(
                "bot1", ws, swb,
                "echo data > /workspace/common/skills/file.md",
                "/workspace/bots/bot1",
            )

    def test_unrelated_path_not_blocked(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb()
        # Write to a non-protected path should be fine
        svc._check_write_protection(
            "bot1", ws, swb,
            "touch /workspace/bots/bot1/notes.md",
            "/workspace/bots/bot1",
        )

    def test_sed_inplace_on_protected_path(self):
        ws = _make_ws(["/workspace/common/skills"])
        swb = _make_swb()
        with pytest.raises(SharedWorkspaceError, match="Write blocked"):
            svc._check_write_protection(
                "bot1", ws, swb,
                "sed -i 's/old/new/' /workspace/common/skills/file.md",
                "/workspace/bots/bot1",
            )
