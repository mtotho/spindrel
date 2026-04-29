import pytest
import httpx

from tests.e2e.harness.client import E2EClient
from tests.e2e.harness.config import E2EConfig


@pytest.mark.asyncio
async def test_list_docker_stacks_reports_missing_deploy_route():
    client = E2EClient(E2EConfig(mode="external", host="example.test", port=80, api_key="key"))
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=client.config.base_url,
        transport=httpx.MockTransport(lambda _request: httpx.Response(404, json={"detail": "Not Found"})),
    )

    with pytest.raises(RuntimeError, match="missing /api/v1/admin/docker-stacks"):
        await client.list_docker_stacks()

    await client.close()


@pytest.mark.asyncio
async def test_get_docker_stack_status_reports_missing_deploy_route():
    client = E2EClient(E2EConfig(mode="external", host="example.test", port=80, api_key="key"))
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=client.config.base_url,
        transport=httpx.MockTransport(lambda _request: httpx.Response(404, json={"detail": "Not Found"})),
    )

    with pytest.raises(RuntimeError, match="missing docker-stack status diagnostics"):
        await client.get_docker_stack_status("browser_automation")

    await client.close()


@pytest.mark.asyncio
async def test_create_channel_session_reports_missing_deploy_route():
    client = E2EClient(E2EConfig(mode="external", host="example.test", port=80, api_key="key"))
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=client.config.base_url,
        transport=httpx.MockTransport(lambda _request: httpx.Response(404, json={"detail": "Not Found"})),
    )

    with pytest.raises(RuntimeError, match="missing /api/v1/channels/\\{channel_id\\}/sessions"):
        await client.create_channel_session("channel-1")

    await client.close()
