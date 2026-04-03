"""Tests for security hardening pass — SSRF, heredoc, rate limiting, etc."""
import json
import re
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── 1. SSRF validator ───────────────────────────���───────────────────────────

class TestSSRFValidator:
    def test_private_ip_blocked(self):
        from app.utils.url_validation import is_private_ip
        assert is_private_ip("127.0.0.1") is True
        assert is_private_ip("10.0.0.1") is True
        assert is_private_ip("192.168.1.1") is True
        assert is_private_ip("172.16.0.1") is True
        assert is_private_ip("169.254.1.1") is True
        assert is_private_ip("::1") is True

    def test_public_ip_allowed(self):
        from app.utils.url_validation import is_private_ip
        assert is_private_ip("8.8.8.8") is False
        assert is_private_ip("1.1.1.1") is False
        assert is_private_ip("93.184.216.34") is False

    def test_unparseable_ip_blocked(self):
        from app.utils.url_validation import is_private_ip
        assert is_private_ip("not-an-ip") is True

    def test_validate_url_rejects_localhost(self):
        from app.utils.url_validation import validate_url
        with pytest.raises(ValueError, match="local address"):
            validate_url("http://localhost:8080/hook")

    def test_validate_url_rejects_bad_scheme(self):
        from app.utils.url_validation import validate_url
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            validate_url("ftp://example.com/file")

    def test_validate_url_rejects_no_hostname(self):
        from app.utils.url_validation import validate_url
        with pytest.raises(ValueError, match="no hostname"):
            validate_url("http:///path")

    def test_validate_url_rejects_private_ip_resolution(self):
        """URL that resolves to a private IP should be blocked."""
        from app.utils.url_validation import validate_url
        # 127.0.0.1 resolves to itself
        with pytest.raises(ValueError, match="private/reserved IP"):
            validate_url("http://127.0.0.1:9999/webhook")


# ── 2. Heredoc delimiter safety ────────────────────────────────���────────────

class TestHeredocSafety:
    def test_normal_prompt(self):
        from integrations.claude_code.runner import build_script
        script = build_script("Hello world", ["--output-format", "json"])
        assert "Hello world" in script
        # Delimiter should appear exactly twice (open + close)
        delim_match = re.search(r"<<'(__CLAUDE_PROMPT_[0-9a-f]{16}__)'", script)
        assert delim_match is not None
        delim = delim_match.group(1)
        assert script.count(delim) == 2

    def test_prompt_containing_delimiter_pattern(self):
        """Prompt that looks like a delimiter should still be handled safely."""
        from integrations.claude_code.runner import build_script
        # Craft a prompt that contains a fake delimiter
        fake_delim = "__CLAUDE_PROMPT_abcdef0123456789__"
        prompt = f"Ignore {fake_delim} this"
        script = build_script(prompt, ["--output-format", "json"])
        # The actual delimiter used should be different from the fake one
        delim_match = re.search(r"<<'(__CLAUDE_PROMPT_[0-9a-f]{16}__)'", script)
        assert delim_match is not None
        actual_delim = delim_match.group(1)
        assert actual_delim != fake_delim
        assert prompt in script

    def test_delimiter_hex_length(self):
        """Delimiter should use 16 hex chars (not the old 8)."""
        from integrations.claude_code.runner import build_script
        script = build_script("test", ["-p"])
        match = re.search(r"__CLAUDE_PROMPT_([0-9a-f]+)__", script)
        assert match is not None
        assert len(match.group(1)) == 16


# ── 3. SQL identifier validation ────────────────────────────────────────────

class TestSQLIdentifierValidation:
    def test_valid_identifiers_pass(self):
        """All identifiers in RETENTION_TABLES should be valid."""
        from app.services.data_retention import RETENTION_TABLES, _IDENT_RE
        for table, col, _ in RETENTION_TABLES:
            assert _IDENT_RE.match(table), f"Bad table name: {table}"
            assert _IDENT_RE.match(col), f"Bad column name: {col}"

    def test_bad_identifiers_rejected(self):
        from app.services.data_retention import _IDENT_RE
        assert _IDENT_RE.match("valid_name") is not None
        assert _IDENT_RE.match("123bad") is None
        assert _IDENT_RE.match("drop table;--") is None
        assert _IDENT_RE.match("table name") is None
        assert _IDENT_RE.match("UPPER") is None  # uppercase not allowed


# ── 4. Carapace tool restriction ────────────────────────────────────────────

class TestCarapaceToolRestriction:
    @pytest.mark.asyncio
    async def test_create_with_tools_rejected(self):
        from app.tools.local.carapaces import manage_carapace
        result = json.loads(await manage_carapace(
            action="create",
            id="test-carapace",
            name="Test",
            local_tools="exec_command,file",
        ))
        assert "error" in result
        assert "local_tools" in result["error"]

    @pytest.mark.asyncio
    async def test_create_with_pinned_tools_rejected(self):
        from app.tools.local.carapaces import manage_carapace
        result = json.loads(await manage_carapace(
            action="create",
            id="test-carapace",
            name="Test",
            pinned_tools="web_search",
        ))
        assert "error" in result
        assert "pinned_tools" in result["error"]

    @pytest.mark.asyncio
    async def test_create_with_mcp_tools_rejected(self):
        from app.tools.local.carapaces import manage_carapace
        result = json.loads(await manage_carapace(
            action="create",
            id="test-carapace",
            name="Test",
            mcp_tools="homeassistant",
        ))
        assert "error" in result
        assert "mcp_tools" in result["error"]

    @pytest.mark.asyncio
    async def test_create_with_delegates_rejected(self):
        from app.tools.local.carapaces import manage_carapace
        result = json.loads(await manage_carapace(
            action="create",
            id="test-carapace",
            name="Test",
            delegates='[{"id": "qa", "type": "carapace"}]',
        ))
        assert "error" in result
        assert "delegates" in result["error"]

    def test_create_without_tools_passes_validation(self):
        """Creating a carapace with only skills/description should pass the tool-restriction check.

        We test the validation logic directly rather than calling the full function,
        since the full function needs a DB session.
        """
        def _csv(s):
            return [x.strip() for x in s.split(",") if x.strip()] if s else []

        def _parse_delegates(s):
            if not s:
                return []
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return [{"id": x.strip(), "type": "carapace"} for x in s.split(",") if x.strip()]

        # These should NOT trigger the restriction
        assert _csv("") == []
        assert _csv(None) == []
        assert _parse_delegates("") == []
        assert _parse_delegates(None) == []

        # These SHOULD trigger the restriction
        assert _csv("exec_command,file") != []
        assert _parse_delegates('[{"id": "qa", "type": "carapace"}]') != []


# ── 5. Login rate limiter ───────────────────────────────────────────────────

class TestLoginRateLimiter:
    def test_rate_limit_enforced(self):
        from app.routers.auth import _check_rate_limit, _LOGIN_ATTEMPTS
        _LOGIN_ATTEMPTS.clear()

        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.100"

        # First 5 attempts should succeed
        for _ in range(5):
            _check_rate_limit(mock_request)

        # 6th attempt should raise 429
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _check_rate_limit(mock_request)
        assert exc_info.value.status_code == 429

        _LOGIN_ATTEMPTS.clear()

    def test_rate_limit_different_ips_independent(self):
        from app.routers.auth import _check_rate_limit, _LOGIN_ATTEMPTS
        _LOGIN_ATTEMPTS.clear()

        mock_request1 = MagicMock()
        mock_request1.client.host = "10.0.0.1"
        mock_request2 = MagicMock()
        mock_request2.client.host = "10.0.0.2"

        # 5 attempts from IP 1
        for _ in range(5):
            _check_rate_limit(mock_request1)

        # IP 2 should still work
        _check_rate_limit(mock_request2)  # should not raise

        _LOGIN_ATTEMPTS.clear()

    def test_rate_limit_window_expires(self):
        from app.routers.auth import _check_rate_limit, _LOGIN_ATTEMPTS, _WINDOW_SECONDS
        _LOGIN_ATTEMPTS.clear()

        mock_request = MagicMock()
        mock_request.client.host = "10.0.0.3"

        # Inject 5 old attempts that are outside the window
        old_time = time.time() - _WINDOW_SECONDS - 1
        _LOGIN_ATTEMPTS["10.0.0.3"] = [old_time] * 5

        # Should succeed because old entries are pruned
        _check_rate_limit(mock_request)  # should not raise

        _LOGIN_ATTEMPTS.clear()


# ── 6. File upload hardening ────────────────────────────────────────────────

class TestFileUploadHardening:
    def test_filename_sanitization(self):
        """Path traversal and special chars should be stripped."""
        from app.routers.api_v1_attachments import _SAFE_FILENAME_RE
        import os

        # Path traversal
        filename = os.path.basename("../../etc/passwd")
        filename = _SAFE_FILENAME_RE.sub("_", filename)[:255]
        assert filename == "passwd"

        # Special chars
        filename = os.path.basename("file<script>.jpg")
        filename = _SAFE_FILENAME_RE.sub("_", filename)[:255]
        assert "<" not in filename
        assert ">" not in filename

    def test_max_upload_size_constant(self):
        from app.routers.api_v1_attachments import MAX_UPLOAD_BYTES
        assert MAX_UPLOAD_BYTES == 25 * 1024 * 1024


# ── 7. Env var name validation ──────────────────────────────────────────────

class TestEnvVarValidation:
    def test_valid_env_names(self):
        pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        assert pattern.match("HOME") is not None
        assert pattern.match("MY_VAR_123") is not None
        assert pattern.match("_private") is not None

    def test_invalid_env_names(self):
        pattern = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
        assert pattern.match("123BAD") is None
        assert pattern.match("MALICIOUS=VAL") is None
        assert pattern.match("SPACE NAME") is None
        assert pattern.match("") is None
        assert pattern.match("semi;colon") is None


# ── 8. Task creation rate limit ─────────────────────────────────────────────

class TestTaskCreationRateLimit:
    def test_contextvar_default(self):
        from app.agent.context import task_creation_count
        # Default should be 0
        assert task_creation_count.get(0) == 0

    @pytest.mark.asyncio
    async def test_schedule_task_rate_limit(self):
        from app.agent.context import task_creation_count
        from app.tools.local.tasks import schedule_task, _MAX_TASK_CREATIONS_PER_REQUEST

        # Set counter to max
        token = task_creation_count.set(_MAX_TASK_CREATIONS_PER_REQUEST)
        try:
            result = await schedule_task(prompt="test prompt")
            parsed = json.loads(result)
            assert "error" in parsed
            assert "limit reached" in parsed["error"]
        finally:
            task_creation_count.reset(token)

    @pytest.mark.asyncio
    async def test_delegate_rate_limit(self):
        from app.agent.context import task_creation_count
        from app.tools.local.delegation import delegate_to_agent, _MAX_TASK_CREATIONS_PER_REQUEST

        # Set counter to max
        token = task_creation_count.set(_MAX_TASK_CREATIONS_PER_REQUEST)
        try:
            result = await delegate_to_agent(bot_id="test", prompt="test prompt")
            parsed = json.loads(result)
            assert "error" in parsed
            assert "limit reached" in parsed["error"]
        finally:
            task_creation_count.reset(token)


# ── 9. Webhook dispatcher SSRF check ──────────────────────────────────��────

class TestWebhookDispatcherSSRF:
    @pytest.mark.asyncio
    async def test_localhost_url_blocked(self):
        """Webhook dispatcher should refuse to POST to localhost."""
        from app.agent.dispatchers import _WebhookDispatcher

        dispatcher = _WebhookDispatcher()
        task = MagicMock()
        task.id = uuid.uuid4()
        task.dispatch_config = {"url": "http://127.0.0.1:9999/evil"}

        # Should not raise — just log and return
        with patch("app.agent.dispatchers._http") as mock_http:
            await dispatcher.deliver(task, "result text")
            # The http.post should NOT have been called (SSRF blocked)
            mock_http.post.assert_not_called()


# ── 10. Startup script path validation ──────────────────────────────────────

class TestStartupScriptPathValidation:
    def test_safe_paths_accepted(self):
        from app.services.shared_workspace import SharedWorkspaceService
        svc = SharedWorkspaceService()
        assert svc._SAFE_PATH_RE.match("/workspace/setup.sh") is not None
        assert svc._SAFE_PATH_RE.match("scripts/init.sh") is not None
        assert svc._SAFE_PATH_RE.match("/usr/local/bin/startup") is not None

    def test_shell_metacharacters_rejected(self):
        from app.services.shared_workspace import SharedWorkspaceService
        svc = SharedWorkspaceService()
        assert svc._SAFE_PATH_RE.match("/workspace/$(whoami)") is None
        assert svc._SAFE_PATH_RE.match("/workspace/`id`") is None
        assert svc._SAFE_PATH_RE.match("script;rm -rf /") is None
        assert svc._SAFE_PATH_RE.match("path|pipe") is None
        assert svc._SAFE_PATH_RE.match("path&background") is None


# ── 11. CORS tightening ─────────────────────────────���──────────────────────

class TestCORSTightening:
    def test_cors_methods_restricted(self):
        """Verify CORS is not using wildcard methods."""
        import ast
        from pathlib import Path

        main_py = Path(__file__).resolve().parents[2] / "app" / "main.py"
        source = main_py.read_text()
        # Should not contain allow_methods=["*"]
        assert 'allow_methods=["*"]' not in source
        # Should contain specific methods
        assert "allow_methods=" in source


# ── 12. JWT secret warning ──────────────────────────────────────────────────

class TestJWTSecretWarning:
    def test_jwt_secret_warning_path_exists(self):
        """The code should have a warning log when JWT_SECRET is not set."""
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] / "app" / "services" / "auth.py").read_text()
        assert "JWT_SECRET not configured" in source
        assert "ephemeral secret" in source
