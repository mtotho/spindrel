from tests.e2e.harness.config import E2EConfig
from tests.e2e.harness.environment import E2EEnvironment


def test_searxng_healthcheck_uses_binary_present_in_upstream_image() -> None:
    compose_text = E2EConfig().compose_file.read_text()

    assert '["CMD", "wget"' in compose_text
    assert '["CMD", "curl", "-sf", "http://localhost:8080/"]' not in compose_text


def test_compose_cmd_includes_overrides_before_project_name(tmp_path) -> None:
    override = tmp_path / "compose.override.yml"
    override.write_text("services: {}\n")
    config = E2EConfig(compose_overrides=[override])
    env = E2EEnvironment(config)

    cmd = env._compose_cmd("up", "-d")

    assert cmd[:7] == [
        "docker",
        "compose",
        "-f",
        str(config.compose_file),
        "-f",
        str(override),
        "-p",
    ]
    assert cmd[-2:] == ["up", "-d"]


def test_config_reads_compose_overrides_from_env(monkeypatch, tmp_path) -> None:
    first = tmp_path / "one.yml"
    second = tmp_path / "two.yml"
    monkeypatch.setenv("E2E_COMPOSE_OVERRIDES", f"{first}:{second}")

    config = E2EConfig.from_env()

    assert config.compose_overrides == [first, second]


def test_external_e2e_get_logs_does_not_shell_to_compose() -> None:
    env = E2EEnvironment(E2EConfig(mode="external", host="example.test", port=8000))

    logs = env.get_logs()

    assert "External E2E mode" in logs
    assert "http://example.test:8000" in logs
