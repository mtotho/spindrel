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

    with pytest.raises(RuntimeError, match="missing both /api/v1/channels/\\{channel_id\\}/sessions"):
        await client.create_channel_session("channel-1")

    await client.close()


@pytest.mark.asyncio
async def test_create_channel_session_uses_reset_fallback_for_legacy_deploy():
    client = E2EClient(E2EConfig(mode="external", host="example.test", port=80, api_key="key"))
    await client._client.aclose()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/channels/channel-1/sessions":
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.url.path == "/api/v1/channels/channel-1/reset":
            return httpx.Response(200, json={"new_session_id": "session-1"})
        return httpx.Response(500)

    client._client = httpx.AsyncClient(
        base_url=client.config.base_url,
        transport=httpx.MockTransport(handler),
    )

    assert await client.create_channel_session("channel-1") == "session-1"

    await client.close()


@pytest.mark.asyncio
async def test_create_channel_session_reports_schema_drift_from_reset_fallback():
    client = E2EClient(E2EConfig(mode="external", host="example.test", port=80, api_key="key"))
    await client._client.aclose()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/channels/channel-1/sessions":
            return httpx.Response(404, json={"detail": "Not Found"})
        if request.url.path == "/api/v1/channels/channel-1/reset":
            return httpx.Response(500, text="Internal Server Error")
        return httpx.Response(500)

    client._client = httpx.AsyncClient(
        base_url=client.config.base_url,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RuntimeError, match="image and database schema are out of sync"):
        await client.create_channel_session("channel-1")

    await client.close()


@pytest.mark.asyncio
async def test_list_channels_reports_schema_drift():
    client = E2EClient(E2EConfig(mode="external", host="example.test", port=80, api_key="key"))
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=client.config.base_url,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(500, json={"detail": "column channels.local_tools_override does not exist"})
        ),
    )

    with pytest.raises(RuntimeError, match="listing admin channels"):
        await client.list_channels()

    await client.close()


@pytest.mark.asyncio
async def test_create_channel_session_reports_stale_channel_id():
    client = E2EClient(E2EConfig(mode="external", host="example.test", port=80, api_key="key"))
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url=client.config.base_url,
        transport=httpx.MockTransport(lambda _request: httpx.Response(404, json={"detail": "Channel not found"})),
    )

    with pytest.raises(RuntimeError, match="channel 'channel-1' was not found"):
        await client.create_channel_session("channel-1")

    await client.close()
