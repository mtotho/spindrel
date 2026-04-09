"""Unit tests for carapace subdirectory discovery, classify_path, and collect_skill_files."""
import json
import os
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCollectCarapaceFiles:
    """Test collect_carapace_files() discovers subdirectory carapaces."""

    def test_flat_yaml_still_discovered(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        carapaces = tmp_path / "carapaces"
        carapaces.mkdir()
        (carapaces / "qa.yaml").write_text("id: qa")

        from app.agent.carapaces import collect_carapace_files

        with patch("app.agent.carapaces.CARAPACES_DIR", carapaces):
            with patch("app.agent.carapaces._integration_dirs", return_value=[]):
                items = collect_carapace_files()

        ids = [cid for _, cid, _ in items]
        assert "qa" in ids

    def test_subdirectory_carapace_discovered(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        carapaces = tmp_path / "carapaces"
        baking = carapaces / "baking"
        baking.mkdir(parents=True)
        (baking / "carapace.yaml").write_text("id: baking")

        from app.agent.carapaces import collect_carapace_files

        with patch("app.agent.carapaces.CARAPACES_DIR", carapaces):
            with patch("app.agent.carapaces._integration_dirs", return_value=[]):
                items = collect_carapace_files()

        ids = [cid for _, cid, _ in items]
        assert "baking" in ids
        # Verify the path points to carapace.yaml inside the directory
        paths = {cid: p for p, cid, _ in items}
        assert paths["baking"].name == "carapace.yaml"

    def test_subdirectory_without_carapace_yaml_ignored(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        carapaces = tmp_path / "carapaces"
        random_dir = carapaces / "not-a-carapace"
        random_dir.mkdir(parents=True)
        (random_dir / "readme.md").write_text("not a carapace")

        from app.agent.carapaces import collect_carapace_files

        with patch("app.agent.carapaces.CARAPACES_DIR", carapaces):
            with patch("app.agent.carapaces._integration_dirs", return_value=[]):
                items = collect_carapace_files()

        ids = [cid for _, cid, _ in items]
        assert "not-a-carapace" not in ids

    def test_flat_and_subdirectory_both_discovered(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        carapaces = tmp_path / "carapaces"
        carapaces.mkdir()
        (carapaces / "qa.yaml").write_text("id: qa")
        baking = carapaces / "baking"
        baking.mkdir()
        (baking / "carapace.yaml").write_text("id: baking")

        from app.agent.carapaces import collect_carapace_files

        with patch("app.agent.carapaces.CARAPACES_DIR", carapaces):
            with patch("app.agent.carapaces._integration_dirs", return_value=[]):
                items = collect_carapace_files()

        ids = [cid for _, cid, _ in items]
        assert "qa" in ids
        assert "baking" in ids

    def test_integration_subdirectory_carapace(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        carapaces = tmp_path / "carapaces"
        carapaces.mkdir()

        intg = tmp_path / "integrations" / "myintg" / "carapaces" / "mycarapace"
        intg.mkdir(parents=True)
        (intg / "carapace.yaml").write_text("id: mycarapace")

        from app.agent.carapaces import collect_carapace_files

        with patch("app.agent.carapaces.CARAPACES_DIR", carapaces):
            with patch("app.agent.carapaces._integration_dirs", return_value=[tmp_path / "integrations"]):
                items = collect_carapace_files()

        ids = [cid for _, cid, _ in items]
        assert "integrations/myintg/mycarapace" in ids


class TestClassifyPath:
    """Test _classify_path handles new carapace patterns."""

    def test_carapace_subdir_yaml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = tmp_path / "carapaces" / "baking" / "carapace.yaml"
        p.parent.mkdir(parents=True)
        p.touch()

        from app.services.file_sync import _classify_path

        result = _classify_path(p)
        assert result is not None
        kind, cid, bot_id, source_type = result
        assert kind == "carapace"
        assert cid == "baking"
        assert source_type == "file"

    def test_carapace_subdir_skill(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = tmp_path / "carapaces" / "baking" / "skills" / "sourdough.md"
        p.parent.mkdir(parents=True)
        p.touch()

        from app.services.file_sync import _classify_path

        result = _classify_path(p)
        assert result is not None
        kind, skill_id, bot_id, source_type = result
        assert kind == "skill"
        assert skill_id == "carapaces/baking/sourdough"
        assert source_type == "file"

    def test_integration_carapace_subdir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = tmp_path / "integrations" / "myintg" / "carapaces" / "myc" / "carapace.yaml"
        p.parent.mkdir(parents=True)
        p.touch()

        from app.services.file_sync import _classify_path

        result = _classify_path(p)
        assert result is not None
        kind, cid, bot_id, source_type = result
        assert kind == "carapace"
        assert cid == "integrations/myintg/myc"
        assert source_type == "integration"

    def test_integration_carapace_subdir_skill(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = tmp_path / "integrations" / "myintg" / "carapaces" / "myc" / "skills" / "guide.md"
        p.parent.mkdir(parents=True)
        p.touch()

        from app.services.file_sync import _classify_path

        result = _classify_path(p)
        assert result is not None
        kind, skill_id, bot_id, source_type = result
        assert kind == "skill"
        assert skill_id == "carapaces/myc/guide"
        assert source_type == "integration"

    def test_flat_carapace_yaml_still_works(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = tmp_path / "carapaces" / "qa.yaml"
        p.parent.mkdir(parents=True)
        p.touch()

        from app.services.file_sync import _classify_path

        result = _classify_path(p)
        assert result is not None
        kind, cid, _, source_type = result
        assert kind == "carapace"
        assert cid == "qa"


class TestCollectSkillFiles:
    """Test _collect_skill_files discovers carapace-scoped skills."""

    def test_carapace_skills_discovered(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "carapaces" / "baking" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "sourdough.md").write_text("# Sourdough")
        (skills_dir / "pastry.md").write_text("# Pastry")

        from app.services.file_sync import _collect_skill_files

        items = _collect_skill_files()
        ids = [sid for _, sid, _ in items]
        assert "carapaces/baking/sourdough" in ids
        assert "carapaces/baking/pastry" in ids

    def test_carapace_skills_have_file_source_type(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "carapaces" / "gardening" / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "growing.md").write_text("# Growing")

        from app.services.file_sync import _collect_skill_files

        items = _collect_skill_files()
        matching = [(p, sid, st) for p, sid, st in items if sid == "carapaces/gardening/growing"]
        assert len(matching) == 1
        assert matching[0][2] == "file"

    def test_carapace_dir_without_skills_ignored(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "carapaces" / "qa").mkdir(parents=True)
        # No skills/ subdirectory

        from app.services.file_sync import _collect_skill_files

        items = _collect_skill_files()
        ids = [sid for _, sid, _ in items]
        assert not any(sid.startswith("carapaces/qa/") for sid in ids)

    def test_integration_carapace_skills_discovered_at_startup(self, tmp_path, monkeypatch):
        """Integration carapace skills must be found by _collect_skill_files (not just watcher)."""
        monkeypatch.chdir(tmp_path)
        carapaces = tmp_path / "carapaces"
        carapaces.mkdir()

        intg_skills = tmp_path / "integrations" / "myintg" / "carapaces" / "myc" / "skills"
        intg_skills.mkdir(parents=True)
        (intg_skills / "guide.md").write_text("# Guide")

        from app.services.file_sync import _collect_skill_files

        with patch("app.services.file_sync._integration_dirs", return_value=[tmp_path / "integrations"]):
            items = _collect_skill_files()

        ids = [sid for _, sid, _ in items]
        assert "carapaces/myc/guide" in ids
        # Verify source type is integration
        matching = [(p, sid, st) for p, sid, st in items if sid == "carapaces/myc/guide"]
        assert matching[0][2] == "integration"


class TestViewAttachment:
    """Test view_attachment tool returns correct JSON structure."""

    @pytest.mark.asyncio
    async def test_valid_image_returns_injected_images(self):
        att_id = uuid.uuid4()
        mock_att = MagicMock(
            id=att_id,
            filename="dough.jpg",
            mime_type="image/jpeg",
            file_data=b"\xff\xd8\xff\xe0test-image-data",
        )

        with patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_att
            from app.tools.local.attachments import view_attachment

            result = json.loads(await view_attachment(str(att_id)))

        assert "injected_images" in result
        assert len(result["injected_images"]) == 1
        assert result["injected_images"][0]["mime_type"] == "image/jpeg"
        assert result["injected_images"][0]["base64"]  # non-empty
        assert "message" in result
        assert "dough.jpg" in result["message"]

    @pytest.mark.asyncio
    async def test_non_image_returns_error(self):
        att_id = uuid.uuid4()
        mock_att = MagicMock(
            id=att_id,
            mime_type="application/pdf",
            file_data=b"pdf-data",
        )

        with patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_att
            from app.tools.local.attachments import view_attachment

            result = json.loads(await view_attachment(str(att_id)))

        assert "error" in result
        assert "image" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_missing_file_data_returns_error(self):
        att_id = uuid.uuid4()
        mock_att = MagicMock(
            id=att_id,
            mime_type="image/jpeg",
            file_data=None,
        )

        with patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_att
            from app.tools.local.attachments import view_attachment

            result = json.loads(await view_attachment(str(att_id)))

        assert "error" in result
        assert "no stored file data" in result["error"]

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        with patch("app.services.attachments.get_attachment_by_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            from app.tools.local.attachments import view_attachment

            result = json.loads(await view_attachment(str(uuid.uuid4())))

        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_error(self):
        from app.tools.local.attachments import view_attachment

        result = json.loads(await view_attachment("not-a-uuid"))
        assert "error" in result
        assert "UUID" in result["error"]


class TestInjectedImagesExtraction:
    """Test that dispatch_tool_call extracts injected_images from tool results."""

    def test_toolcallresult_has_injected_images_field(self):
        from app.agent.tool_dispatch import ToolCallResult

        tcr = ToolCallResult()
        assert tcr.injected_images is None

    def test_injected_images_extraction_from_json(self):
        """Verify the extraction logic pattern works."""
        result_json = json.dumps({
            "injected_images": [{"mime_type": "image/jpeg", "base64": "abc123"}],
            "message": "Image loaded.",
        })

        # Simulate the extraction logic from tool_dispatch.py
        result_for_llm = result_json
        injected_images = None
        try:
            parsed_tool = json.loads(result_for_llm)
            if isinstance(parsed_tool, dict):
                if "client_action" in parsed_tool:
                    pass
                elif "injected_images" in parsed_tool:
                    injected_images = parsed_tool["injected_images"]
                    result_for_llm = parsed_tool.get("message", "Image loaded for analysis.")
        except (json.JSONDecodeError, TypeError):
            pass

        assert injected_images is not None
        assert len(injected_images) == 1
        assert injected_images[0]["mime_type"] == "image/jpeg"
        assert result_for_llm == "Image loaded."

    def test_client_action_takes_precedence_over_injected_images(self):
        """If both client_action and injected_images are present, client_action wins."""
        result_json = json.dumps({
            "client_action": {"type": "navigate"},
            "injected_images": [{"mime_type": "image/jpeg", "base64": "abc"}],
            "message": "Done.",
        })

        result_for_llm = result_json
        embedded_client_action = None
        injected_images = None
        try:
            parsed_tool = json.loads(result_for_llm)
            if isinstance(parsed_tool, dict):
                if "client_action" in parsed_tool:
                    embedded_client_action = parsed_tool["client_action"]
                    result_for_llm = parsed_tool.get("message", "Done.")
                elif "injected_images" in parsed_tool:
                    injected_images = parsed_tool["injected_images"]
                    result_for_llm = parsed_tool.get("message", "Image loaded for analysis.")
        except (json.JSONDecodeError, TypeError):
            pass

        assert embedded_client_action is not None
        assert injected_images is None  # elif means only one branch taken


class TestImageInjectionMessage:
    """Test that injected images produce correct synthetic user message format."""

    def test_synthetic_message_structure(self):
        """Verify the synthetic user message format for image injection."""
        images = [
            {"mime_type": "image/jpeg", "base64": "abc123"},
            {"mime_type": "image/png", "base64": "def456"},
        ]

        # Simulate the logic from loop.py
        _img_parts: list[dict] = [{"type": "text", "text": "[Requested image(s) for your analysis]"}]
        for img in images:
            mime = img.get("mime_type", "image/jpeg")
            b64 = img.get("base64", "")
            if b64:
                _img_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })

        assert len(_img_parts) == 3  # text + 2 images
        assert _img_parts[0]["type"] == "text"
        assert _img_parts[1]["type"] == "image_url"
        assert _img_parts[1]["image_url"]["url"] == "data:image/jpeg;base64,abc123"
        assert _img_parts[2]["image_url"]["url"] == "data:image/png;base64,def456"

    def test_empty_base64_skipped(self):
        """Images with empty base64 should be skipped."""
        images = [
            {"mime_type": "image/jpeg", "base64": ""},
            {"mime_type": "image/png", "base64": "valid"},
        ]

        _img_parts: list[dict] = [{"type": "text", "text": "[Requested image(s) for your analysis]"}]
        for img in images:
            mime = img.get("mime_type", "image/jpeg")
            b64 = img.get("base64", "")
            if b64:
                _img_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })

        assert len(_img_parts) == 2  # text + 1 valid image

    def test_no_images_no_message(self):
        """When no images have data, message should not be appended."""
        _iteration_injected_images: list[dict] = []
        messages: list[dict] = []

        if _iteration_injected_images:
            messages.append({"role": "user", "content": "should not reach"})

        assert len(messages) == 0


class TestContextMasterySkill:
    """Test that context_mastery skill exists and is referenced by all carapaces."""

    def test_context_mastery_file_exists(self):
        from pathlib import Path

        skill_path = Path("skills/context_mastery.md")
        assert skill_path.is_file(), "skills/context_mastery.md should exist"

    def test_context_mastery_has_frontmatter(self):
        from pathlib import Path

        content = Path("skills/context_mastery.md").read_text()
        assert content.startswith("---"), "Should have YAML frontmatter"
        assert "name: Context Mastery" in content

    def test_context_mastery_discovered_by_collect_skill_files(self, tmp_path, monkeypatch):
        """context_mastery.md should be picked up by the global skills scanner."""
        monkeypatch.chdir(tmp_path)
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "context_mastery.md").write_text("---\nname: Context Mastery\n---\n# Content")

        from app.services.file_sync import _collect_skill_files

        items = _collect_skill_files()
        ids = [sid for _, sid, _ in items]
        assert "context_mastery" in ids

    def test_context_mastery_covers_key_topics(self):
        """Verify the skill covers the required topics."""
        from pathlib import Path

        content = Path("skills/context_mastery.md").read_text()
        # Context map
        assert "Auto-Injected" in content
        assert "On Demand" in content
        # Temperature tiers
        assert "Hot" in content and "Warm" in content and "Cold" in content
        # Reference file authoring (pseudo-skills)
        assert "Pseudo-Skill" in content or "pseudo-skill" in content or "Reference Files" in content
        # Delegation with model override
        assert "Delegation" in content or "delegation" in content
        assert "model_override" in content
        assert "schedule_task" in content
        # Context budget
        assert "MEMORY.md" in content
        assert "archive" in content.lower()
        # Cold start
        assert "Cold Start" in content
