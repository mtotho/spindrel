"""Unit tests for workspace skills discovery, embedding, and retrieval."""
import hashlib
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.services.workspace_skills import (
    WorkspaceSkill,
    _mode_from_path,
    _skill_id,
    _display_name,
    discover_workspace_skills,
    get_workspace_skills_for_bot,
    list_workspace_skill_files,
)


# ---------------------------------------------------------------------------
# _mode_from_path tests
# ---------------------------------------------------------------------------

class TestModeFromPath:
    def test_pinned_subdir(self):
        assert _mode_from_path("common/skills/pinned/coding.md") == "pinned"

    def test_rag_subdir(self):
        assert _mode_from_path("common/skills/rag/knowledge.md") == "on_demand"

    def test_on_demand_subdir(self):
        assert _mode_from_path("common/skills/on-demand/reference.md") == "on_demand"

    def test_toplevel_defaults_pinned(self):
        assert _mode_from_path("common/skills/quickstart.md") == "pinned"

    def test_bot_pinned(self):
        assert _mode_from_path("bots/coder/skills/pinned/style.md") == "pinned"

    def test_bot_rag(self):
        assert _mode_from_path("bots/coder/skills/rag/api.md") == "on_demand"

    def test_bot_on_demand(self):
        assert _mode_from_path("bots/coder/skills/on-demand/ref.md") == "on_demand"

    def test_bot_toplevel_defaults_pinned(self):
        assert _mode_from_path("bots/coder/skills/local.md") == "pinned"

    def test_no_skills_in_path(self):
        assert _mode_from_path("common/prompts/base.md") == "pinned"


# ---------------------------------------------------------------------------
# _skill_id tests
# ---------------------------------------------------------------------------

class TestSkillId:
    def test_deterministic(self):
        id1 = _skill_id("abc-def-123", "common/skills/pinned/test.md")
        id2 = _skill_id("abc-def-123", "common/skills/pinned/test.md")
        assert id1 == id2

    def test_different_paths_different_ids(self):
        id1 = _skill_id("abc-def-123", "common/skills/pinned/a.md")
        id2 = _skill_id("abc-def-123", "common/skills/pinned/b.md")
        assert id1 != id2

    def test_format(self):
        sid = _skill_id("abcdef12-3456-7890-abcd-ef1234567890", "common/skills/test.md")
        assert sid.startswith("ws:")


# ---------------------------------------------------------------------------
# _display_name tests
# ---------------------------------------------------------------------------

class TestDisplayName:
    def test_simple(self):
        assert _display_name("common/skills/pinned/coding.md") == "Coding"

    def test_with_dashes(self):
        assert _display_name("common/skills/api-reference.md") == "Api Reference"

    def test_with_underscores(self):
        assert _display_name("common/skills/my_skill.md") == "My Skill"


# ---------------------------------------------------------------------------
# discover_workspace_skills tests
# ---------------------------------------------------------------------------

def _mock_list_files(workspace_id, path):
    """Mock workspace file listings for test scenarios."""
    listings = {
        "common/skills": [
            {"name": "quickstart.md", "is_dir": False, "path": "common/skills/quickstart.md"},
            {"name": "pinned", "is_dir": True, "path": "common/skills/pinned"},
            {"name": "rag", "is_dir": True, "path": "common/skills/rag"},
            {"name": "on-demand", "is_dir": True, "path": "common/skills/on-demand"},
            {"name": "README.txt", "is_dir": False, "path": "common/skills/README.txt"},
        ],
        "common/skills/pinned": [
            {"name": "coding.md", "is_dir": False, "path": "common/skills/pinned/coding.md"},
        ],
        "common/skills/rag": [
            {"name": "knowledge.md", "is_dir": False, "path": "common/skills/rag/knowledge.md"},
        ],
        "common/skills/on-demand": [
            {"name": "reference.md", "is_dir": False, "path": "common/skills/on-demand/reference.md"},
        ],
        "bots/coder/skills": [
            {"name": "pinned", "is_dir": True, "path": "bots/coder/skills/pinned"},
        ],
        "bots/coder/skills/pinned": [
            {"name": "style.md", "is_dir": False, "path": "bots/coder/skills/pinned/style.md"},
        ],
    }
    return listings.get(path, [])


def _mock_read_file(workspace_id, path):
    """Mock file reads."""
    return {"path": path, "content": f"# Content of {path}\n\nSome text.", "size": 100}


class TestDiscoverWorkspaceSkills:
    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_discover_common_skills_pinned(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        skills = discover_workspace_skills("ws-123")
        pinned = [s for s in skills if s.mode == "pinned"]
        # quickstart.md (top-level, defaults to pinned) + coding.md (in pinned/)
        pinned_paths = [s.source_path for s in pinned]
        assert "common/skills/quickstart.md" in pinned_paths
        assert "common/skills/pinned/coding.md" in pinned_paths

    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_discover_rag_subdir_maps_to_on_demand(self, mock_svc):
        """The rag/ subdirectory now maps to on_demand mode."""
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        skills = discover_workspace_skills("ws-123")
        from_rag_dir = [s for s in skills if "rag/knowledge.md" in s.source_path]
        assert len(from_rag_dir) == 1
        assert from_rag_dir[0].mode == "on_demand"

    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_discover_common_skills_on_demand(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        skills = discover_workspace_skills("ws-123")
        od = [s for s in skills if s.mode == "on_demand"]
        # Both rag/knowledge.md and on-demand/reference.md should be on_demand now
        assert len(od) == 2
        paths = {s.source_path for s in od}
        assert "common/skills/rag/knowledge.md" in paths
        assert "common/skills/on-demand/reference.md" in paths

    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_discover_common_skills_toplevel_defaults_pinned(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        skills = discover_workspace_skills("ws-123")
        quickstart = [s for s in skills if "quickstart.md" in s.source_path]
        assert len(quickstart) == 1
        assert quickstart[0].mode == "pinned"

    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_discover_bot_skills(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        skills = discover_workspace_skills("ws-123", bot_id="coder")
        bot_skills = [s for s in skills if s.bot_id == "coder"]
        assert len(bot_skills) == 1
        assert bot_skills[0].source_path == "bots/coder/skills/pinned/style.md"
        assert bot_skills[0].mode == "pinned"

    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_discover_combined(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        skills = discover_workspace_skills("ws-123", bot_id="coder")
        # Should have common (quickstart + coding + knowledge + reference) + bot (style)
        assert len(skills) == 5

    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_discover_no_skills_dir(self, mock_svc):
        from app.services.shared_workspace import SharedWorkspaceError
        mock_svc.list_files.side_effect = SharedWorkspaceError("not found")
        skills = discover_workspace_skills("ws-123")
        assert skills == []

    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_non_md_files_ignored(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        skills = discover_workspace_skills("ws-123")
        # README.txt should not be in results
        paths = [s.source_path for s in skills]
        assert not any(p.endswith(".txt") for p in paths)

    @patch("app.services.workspace_skills.shared_workspace_service")
    def test_content_hash_computed(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        skills = discover_workspace_skills("ws-123")
        for s in skills:
            expected_hash = hashlib.sha256(s.content.encode()).hexdigest()
            assert s.content_hash == expected_hash


# ---------------------------------------------------------------------------
# get_workspace_skills_for_bot tests
# ---------------------------------------------------------------------------

class TestGetWorkspaceSkillsForBot:
    @pytest.mark.asyncio
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_groups_by_mode(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        result = await get_workspace_skills_for_bot("ws-123", "coder")
        assert "pinned" in result
        assert "on_demand" in result
        # quickstart.md + coding.md + style.md are pinned
        assert len(result["pinned"]) == 3
        # rag/ now maps to on_demand, so on_demand has both rag/knowledge.md + on-demand/reference.md
        assert len(result["on_demand"]) == 2

    @pytest.mark.asyncio
    @patch("app.services.workspace_skills.shared_workspace_service")
    async def test_common_plus_bot_skills_merged(self, mock_svc):
        mock_svc.list_files.side_effect = _mock_list_files
        mock_svc.read_file.side_effect = _mock_read_file
        result = await get_workspace_skills_for_bot("ws-123", "coder")
        all_skills = result["pinned"] + result["on_demand"]
        # Common (4) + bot-specific (1) = 5
        assert len(all_skills) == 5
        bot_skills = [s for s in all_skills if s.bot_id == "coder"]
        assert len(bot_skills) == 1
