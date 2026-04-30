from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_spindrel_cli():
    script = REPO_ROOT / "scripts" / "spindrel"
    loader = importlib.machinery.SourceFileLoader("spindrel_cli_for_test", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_spindrel_cli_pull_defaults_to_latest_release_tag(monkeypatch):
    cli = _load_spindrel_cli()
    commands: list[str] = []

    def fake_run(command, *args, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "dc", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli, "_latest_release_tag", lambda repo: "v9.9.9")
    monkeypatch.setattr(cli, "_build_integration_uis", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "_rebuild_ui", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "systemd_restart", lambda *args, **kwargs: None)

    cli.docker_pull("/opt/thoth-server", SimpleNamespace())
    cli.systemd_pull("/opt/thoth-server", SimpleNamespace())

    assert commands == [
        "git -C /opt/thoth-server fetch origin --tags --prune",
        "git -C /opt/thoth-server checkout --detach refs/tags/v9.9.9",
        "git -C /opt/thoth-server fetch origin --tags --prune",
        "git -C /opt/thoth-server checkout --detach refs/tags/v9.9.9",
    ]
    assert all("origin master" not in command for command in commands)


def test_spindrel_cli_pull_can_target_development(monkeypatch):
    cli = _load_spindrel_cli()
    commands: list[str] = []

    def fake_run(command, *args, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli, "dc", lambda *args, **kwargs: SimpleNamespace(returncode=0))

    cli.docker_pull("/opt/thoth-server", SimpleNamespace(development=True))

    assert commands == [
        "git -C /opt/thoth-server fetch origin development && "
        "(git -C /opt/thoth-server switch development || "
        "git -C /opt/thoth-server switch -c development --track origin/development) && "
        "git -C /opt/thoth-server pull --rebase origin development"
    ]


@pytest.mark.asyncio
async def test_local_git_pull_tool_defaults_to_stable_tag(monkeypatch):
    from app.tools.local import git_pull as git_pull_tool

    calls = []

    class Proc:
        returncode = 0
        stdout = b""

        async def communicate(self):
            return self.stdout, b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append(args)
        proc = Proc()
        if args[-1] == "--sort=-v:refname":
            proc.stdout = b"v9.9.9\nv1.0.0\n"
        else:
            proc.stdout = b"Already up to date."
        return proc

    monkeypatch.setattr(git_pull_tool.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await git_pull_tool.git_pull()

    assert calls == [
        ("git", "-C", calls[0][2], "fetch", "origin", "--tags", "--prune"),
        ("git", "-C", calls[0][2], "tag", "--sort=-v:refname"),
        ("git", "-C", calls[0][2], "checkout", "--detach", "refs/tags/v9.9.9"),
    ]


@pytest.mark.asyncio
async def test_local_git_pull_tool_can_pull_development(monkeypatch):
    from app.tools.local import git_pull as git_pull_tool

    calls = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append(args)
        return Proc()

    monkeypatch.setattr(git_pull_tool.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await git_pull_tool.git_pull(channel="development")

    assert calls == [
        ("git", "-C", calls[0][2], "fetch", "origin", "development"),
        ("git", "-C", calls[0][2], "switch", "development"),
        ("git", "-C", calls[0][2], "pull", "--rebase", "origin", "development"),
    ]
