from tests.e2e.harness.config import E2EConfig
from tests.e2e.harness.environment import E2EEnvironment


def test_external_e2e_get_logs_does_not_shell_to_compose() -> None:
    env = E2EEnvironment(E2EConfig(mode="external", host="example.test", port=8000))

    logs = env.get_logs()

    assert "External E2E mode" in logs
    assert "http://example.test:8000" in logs
