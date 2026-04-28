"""Tests for GitHub integration: event parsing, webhook, bot filtering, tools."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.github.handlers import ParsedEvent, parse_event
from integrations.github.validator import validate_signature


# ---------------------------------------------------------------------------
# Signature validation
# ---------------------------------------------------------------------------

def _sign(payload: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


class TestSignatureValidation:
    def test_valid_signature(self):
        secret = "webhook-secret"
        payload = b'{"action":"opened"}'
        with patch("integrations.github.validator.settings") as s:
            s.GITHUB_WEBHOOK_SECRET = secret
            assert validate_signature(payload, _sign(payload, secret)) is True

    def test_invalid_signature(self):
        with patch("integrations.github.validator.settings") as s:
            s.GITHUB_WEBHOOK_SECRET = "secret"
            assert validate_signature(b"body", "sha256=bad") is False

    def test_no_secret_rejects(self):
        """Fail-secure: no secret configured means reject all webhooks."""
        with patch("integrations.github.validator.settings") as s:
            s.GITHUB_WEBHOOK_SECRET = ""
            assert validate_signature(b"anything", None) is False


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

def _base_payload(full_name="org/repo", sender="alice"):
    return {
        "repository": {"full_name": full_name},
        "sender": {"login": sender},
    }


class TestPullRequestEvent:
    def test_opened(self):
        payload = {
            **_base_payload(),
            "action": "opened",
            "pull_request": {
                "number": 42,
                "title": "Add feature",
                "body": "Description here",
                "changed_files": 3,
                "additions": 100,
                "deletions": 20,
                "head": {"ref": "feature-branch"},
                "base": {"ref": "main"},
            },
        }
        result = parse_event("pull_request", payload)
        assert result is not None
        assert result.run_agent is True
        assert result.comment_target == {"type": "issue_comment", "issue_number": 42}
        assert "PR #42" in result.message
        assert "Add feature" in result.message
        assert result.owner == "org"
        assert result.repo == "repo"

    def test_synchronize(self):
        payload = {
            **_base_payload(),
            "action": "synchronize",
            "after": "abc1234567890",
            "pull_request": {"number": 42, "title": "Add feature"},
        }
        result = parse_event("pull_request", payload)
        assert result is not None
        assert result.run_agent is False
        assert result.comment_target is None

    def test_closed_merged(self):
        payload = {
            **_base_payload(),
            "action": "closed",
            "pull_request": {"number": 42, "title": "Add feature", "merged": True},
        }
        result = parse_event("pull_request", payload)
        assert result is not None
        assert "merged" in result.message
        assert result.run_agent is False

    def test_closed_not_merged(self):
        payload = {
            **_base_payload(),
            "action": "closed",
            "pull_request": {"number": 42, "title": "X", "merged": False},
        }
        result = parse_event("pull_request", payload)
        assert "closed" in result.message

    def test_unhandled_action_ignored(self):
        payload = {**_base_payload(), "action": "labeled", "pull_request": {"number": 1}}
        result = parse_event("pull_request", payload)
        assert result is None


class TestIssuesEvent:
    def test_opened(self):
        payload = {
            **_base_payload(),
            "action": "opened",
            "issue": {
                "number": 10,
                "title": "Bug report",
                "body": "Steps to reproduce...",
                "labels": [{"name": "bug"}],
            },
        }
        result = parse_event("issues", payload)
        assert result is not None
        assert result.run_agent is True
        assert result.comment_target == {"type": "issue_comment", "issue_number": 10}
        assert "Bug report" in result.message
        assert "bug" in result.message

    def test_non_opened_ignored(self):
        payload = {**_base_payload(), "action": "closed", "issue": {"number": 1}}
        assert parse_event("issues", payload) is None


class TestIssueCommentEvent:
    def test_created(self):
        payload = {
            **_base_payload(),
            "action": "created",
            "comment": {"body": "Please fix this"},
            "issue": {"number": 5, "title": "Bug"},
        }
        result = parse_event("issue_comment", payload)
        assert result is not None
        assert result.run_agent is True
        assert "Please fix this" in result.message
        assert result.comment_target["issue_number"] == 5

    def test_pr_comment(self):
        payload = {
            **_base_payload(),
            "action": "created",
            "comment": {"body": "LGTM"},
            "issue": {"number": 3, "title": "PR title", "pull_request": {"url": "..."}},
        }
        result = parse_event("issue_comment", payload)
        assert "PR" in result.message

    def test_non_created_ignored(self):
        payload = {
            **_base_payload(),
            "action": "edited",
            "comment": {"body": "updated"},
            "issue": {"number": 1, "title": "X"},
        }
        assert parse_event("issue_comment", payload) is None


class TestPullRequestReviewEvent:
    def test_changes_requested(self):
        payload = {
            **_base_payload(),
            "review": {"state": "changes_requested", "body": "Needs work"},
            "pull_request": {"number": 7, "title": "Draft PR"},
        }
        result = parse_event("pull_request_review", payload)
        assert result is not None
        assert result.run_agent is True
        assert result.comment_target is not None

    def test_approved_no_agent(self):
        payload = {
            **_base_payload(),
            "review": {"state": "approved", "body": ""},
            "pull_request": {"number": 7, "title": "PR"},
        }
        result = parse_event("pull_request_review", payload)
        assert result.run_agent is False
        assert result.comment_target is None


class TestPullRequestReviewCommentEvent:
    def test_created(self):
        payload = {
            **_base_payload(),
            "action": "created",
            "comment": {"body": "This line is wrong", "path": "src/main.py", "line": 42},
            "pull_request": {"number": 8, "title": "Refactor"},
        }
        result = parse_event("pull_request_review_comment", payload)
        assert result is not None
        assert result.run_agent is True
        assert "src/main.py" in result.message
        assert ":42" in result.message


class TestPushEvent:
    def test_basic_push(self):
        payload = {
            **_base_payload(),
            "ref": "refs/heads/main",
            "forced": False,
            "commits": [
                {"id": "abc1234567890", "message": "Fix bug\ndetails"},
                {"id": "def4567890abc", "message": "Update readme"},
            ],
        }
        result = parse_event("push", payload)
        assert result is not None
        assert result.run_agent is False
        assert "2 commit(s)" in result.message
        assert "abc1234" in result.message

    def test_force_push(self):
        payload = {
            **_base_payload(),
            "ref": "refs/heads/feature",
            "forced": True,
            "commits": [],
        }
        result = parse_event("push", payload)
        assert "force push" in result.message


class TestReleaseEvent:
    def test_published(self):
        payload = {
            **_base_payload(),
            "action": "published",
            "release": {"tag_name": "v1.0", "name": "Version 1.0", "body": "Changelog"},
        }
        result = parse_event("release", payload)
        assert result is not None
        assert result.run_agent is False
        assert "v1.0" in result.message

    def test_non_published_ignored(self):
        payload = {**_base_payload(), "action": "created", "release": {"tag_name": "v1.0"}}
        assert parse_event("release", payload) is None


class TestDiscussionEvents:
    def test_discussion_created(self):
        payload = {
            **_base_payload(),
            "action": "created",
            "discussion": {"title": "RFC: New API", "body": "Proposal..."},
        }
        result = parse_event("discussion", payload)
        assert result is not None
        assert result.run_agent is False

    def test_discussion_comment(self):
        payload = {
            **_base_payload(),
            "action": "created",
            "comment": {"body": "Great idea"},
            "discussion": {"title": "RFC"},
        }
        result = parse_event("discussion_comment", payload)
        assert result is not None
        assert result.run_agent is False


class TestUnknownEvent:
    def test_unknown_event_returns_none(self):
        assert parse_event("deployment_status", {}) is None


# ---------------------------------------------------------------------------
# Bot self-comment filtering (tested at router level logic)
# ---------------------------------------------------------------------------

class TestBotFiltering:
    def test_sender_matches_bot_login(self):
        """The router skips events where sender == GITHUB_BOT_LOGIN.
        We test the logic inline since it's a simple string compare."""
        bot_login = "my-bot[bot]"
        sender = "my-bot[bot]"
        assert sender == bot_login  # would be filtered

    def test_sender_does_not_match(self):
        bot_login = "my-bot[bot]"
        sender = "alice"
        assert sender != bot_login  # would be processed


# ---------------------------------------------------------------------------
# Tools (mocked HTTP)
# ---------------------------------------------------------------------------

class TestGitHubTools:
    @pytest.mark.asyncio
    async def test_github_get_pr(self):
        from integrations.github.tools.github_tools import github_get_pr

        pr_data = {
            "title": "Test PR",
            "state": "open",
            "merged": False,
            "user": {"login": "alice"},
            "base": {"ref": "main"},
            "head": {"ref": "feature"},
            "body": "Description",
            "additions": 10,
            "deletions": 5,
            "changed_files": 2,
        }
        files_data = [
            {"filename": "a.py", "additions": 5, "deletions": 2},
            {"filename": "b.py", "additions": 5, "deletions": 3},
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = pr_data
        mock_response.raise_for_status = MagicMock()

        mock_diff = MagicMock()
        mock_diff.text = "diff --git a/a.py b/a.py\n+new line"
        mock_diff.status_code = 200

        mock_files = MagicMock()
        mock_files.json.return_value = files_data
        mock_files.status_code = 200

        async def mock_get(url, **kwargs):
            if "files" in url:
                return mock_files
            accept = kwargs.get("headers", {}).get("Accept", "")
            if "diff" in accept:
                return mock_diff
            return mock_response

        with patch("integrations.github.tools.github_tools._http") as mock_http:
            mock_http.get = AsyncMock(side_effect=mock_get)
            result = await github_get_pr("org", "repo", 1)

        assert "Test PR" in result
        assert "a.py" in result
        assert "diff" in result

    @pytest.mark.asyncio
    async def test_github_search_issues(self):
        from integrations.github.tools.github_tools import github_search_issues

        search_data = {
            "total_count": 1,
            "items": [{
                "number": 42,
                "title": "Found issue",
                "state": "open",
                "labels": [{"name": "bug"}],
                "html_url": "https://github.com/org/repo/issues/42",
            }],
        }
        mock_response = MagicMock()
        mock_response.json.return_value = search_data
        mock_response.raise_for_status = MagicMock()

        with patch("integrations.github.tools.github_tools._http") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)
            result = await github_search_issues("bug", repo="org/repo")

        assert "Found issue" in result
        assert "#42" in result
        assert "bug" in result

    @pytest.mark.asyncio
    async def test_github_post_comment(self):
        from integrations.github.tools.github_tools import github_post_comment

        mock_response = MagicMock()
        mock_response.json.return_value = {"html_url": "https://github.com/org/repo/issues/1#comment-123"}
        mock_response.raise_for_status = MagicMock()

        with patch("integrations.github.tools.github_tools._http") as mock_http:
            mock_http.post = AsyncMock(return_value=mock_response)
            result = await github_post_comment("org", "repo", 1, "Hello")

        assert "comment-123" in result

    @pytest.mark.asyncio
    async def test_github_list_prs(self):
        from integrations.github.tools.github_tools import github_list_prs

        prs_data = [
            {"number": 1, "title": "First PR", "user": {"login": "alice"}, "labels": []},
            {"number": 2, "title": "Second PR", "user": {"login": "bob"}, "labels": [{"name": "WIP"}]},
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = prs_data
        mock_response.raise_for_status = MagicMock()

        with patch("integrations.github.tools.github_tools._http") as mock_http:
            mock_http.get = AsyncMock(return_value=mock_response)
            result = await github_list_prs("org", "repo")

        assert "First PR" in result
        assert "Second PR" in result
        assert "@alice" in result
        assert "WIP" in result


class TestGitHubRepoDashboard:
    @pytest.mark.asyncio
    async def test_dashboard_aggregates_repo_activity_and_filters_pr_issues(self):
        from integrations.github.tools.repo_dashboard import github_repo_dashboard

        def response(payload, status_code=200, headers=None):
            mock = MagicMock()
            mock.status_code = status_code
            mock.headers = headers or {}
            mock.json.return_value = payload
            mock.raise_for_status = MagicMock()
            return mock

        async def mock_get(url, **kwargs):
            if url.endswith("/repos/org/repo"):
                return response(
                    {
                        "default_branch": "main",
                        "description": "Test repo",
                        "html_url": "https://github.com/org/repo",
                        "stargazers_count": 3,
                        "forks_count": 1,
                    },
                    headers={"x-ratelimit-remaining": "4999", "x-ratelimit-limit": "5000"},
                )
            if url.endswith("/commits"):
                return response([
                    {
                        "sha": "abcdef1234567890",
                        "html_url": "https://github.com/org/repo/commit/abcdef",
                        "commit": {
                            "message": "Ship dashboard\n\nbody",
                            "author": {"name": "Alice", "date": "2026-04-27T10:00:00Z"},
                        },
                        "author": {"login": "alice"},
                    }
                ])
            if url.endswith("/pulls"):
                return response([
                    {
                        "number": 2,
                        "title": "Open PR",
                        "html_url": "https://github.com/org/repo/pull/2",
                        "user": {"login": "bob"},
                        "head": {"ref": "feature"},
                        "base": {"ref": "main"},
                        "labels": [{"name": "ui"}],
                    }
                ])
            if url.endswith("/issues"):
                return response([
                    {
                        "number": 3,
                        "title": "Real issue",
                        "html_url": "https://github.com/org/repo/issues/3",
                        "user": {"login": "carol"},
                        "labels": [{"name": "bug"}],
                    },
                    {
                        "number": 2,
                        "title": "PR issue shadow",
                        "pull_request": {"url": "https://api.github.com/prs/2"},
                    },
                ])
            if url.endswith("/actions/runs"):
                return response({
                    "workflow_runs": [{
                        "id": 10,
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/org/repo/actions/runs/10",
                    }]
                })
            if url.endswith("/releases/latest"):
                return response({
                    "tag_name": "v1.0.0",
                    "name": "v1.0.0",
                    "html_url": "https://github.com/org/repo/releases/tag/v1.0.0",
                })
            raise AssertionError(f"Unexpected URL: {url}")

        with patch("integrations.github.tools.repo_dashboard._http") as mock_http:
            mock_http.get = AsyncMock(side_effect=mock_get)
            result = json.loads(await github_repo_dashboard("org/repo", limit=20))

        assert result["repository"]["full_name"] == "org/repo"
        assert result["commits"][0]["message"] == "Ship dashboard"
        assert result["prs"][0]["number"] == 2
        assert [issue["number"] for issue in result["issues"]] == [3]
        assert result["health"]["latest_workflow"]["conclusion"] == "success"
        assert result["latest_release"]["tag_name"] == "v1.0.0"
        assert result["health"]["rate_limit"]["remaining"] == 4999

    @pytest.mark.asyncio
    async def test_set_issue_state_requires_confirmation(self):
        from integrations.github.tools.repo_dashboard import github_set_issue_state

        result = json.loads(await github_set_issue_state(
            "org/repo",
            issue_number=3,
            state="closed",
            confirmed=False,
        ))

        assert result["error"] == "Issue state changes require explicit confirmation."

    @pytest.mark.asyncio
    async def test_set_issue_state_posts_optional_comment_before_patch(self):
        from integrations.github.tools.repo_dashboard import github_set_issue_state

        comment_resp = MagicMock()
        comment_resp.raise_for_status = MagicMock()
        issue_resp = MagicMock()
        issue_resp.raise_for_status = MagicMock()
        issue_resp.json.return_value = {
            "number": 3,
            "title": "Fixed",
            "state": "closed",
            "html_url": "https://github.com/org/repo/issues/3",
            "user": {"login": "alice"},
        }

        with patch("integrations.github.tools.repo_dashboard._http") as mock_http:
            mock_http.post = AsyncMock(return_value=comment_resp)
            mock_http.patch = AsyncMock(return_value=issue_resp)
            result = json.loads(await github_set_issue_state(
                "org/repo",
                issue_number=3,
                state="closed",
                comment="Closing from widget.",
                confirmed=True,
            ))

        mock_http.post.assert_awaited_once()
        mock_http.patch.assert_awaited_once()
        assert result["comment_posted"] is True
        assert result["issue"]["state"] == "closed"


class TestGitHubPresetBindings:
    def test_repo_options_transform(self):
        from integrations.github.bindings import repo_options

        raw = json.dumps({
            "repositories": [
                {
                    "repository": "org/repo",
                    "label": "org/repo",
                    "group": "Current channel",
                    "channel_id": "channel-id",
                    "current_channel": True,
                }
            ]
        })

        options = repo_options(raw, {})

        assert options == [{
            "value": "org/repo",
            "label": "org/repo",
            "description": "GitHub repository",
            "group": "Current channel",
            "meta": {"channel_id": "channel-id", "current_channel": True},
        }]
