"""Tests for BlueBubbles REST API helpers."""
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from integrations.bluebubbles.bb_api import ping, send_text, send_attachment, query_chats, get_chat_messages


@pytest.fixture
def mock_client():
    """Create a mock httpx.AsyncClient."""
    return AsyncMock(spec=httpx.AsyncClient)


class TestPing:
    @pytest.mark.asyncio
    async def test_ping_success(self, mock_client):
        mock_client.get.return_value = MagicMock(status_code=200)
        result = await ping(mock_client, "http://bb:1234", "pass123")
        assert result is True
        mock_client.get.assert_called_once_with(
            "http://bb:1234/api/v1/server/info",
            params={"password": "pass123"},
        )

    @pytest.mark.asyncio
    async def test_ping_failure(self, mock_client):
        mock_client.get.return_value = MagicMock(status_code=500)
        result = await ping(mock_client, "http://bb:1234", "pass123")
        assert result is False

    @pytest.mark.asyncio
    async def test_ping_exception(self, mock_client):
        mock_client.get.side_effect = Exception("connection refused")
        result = await ping(mock_client, "http://bb:1234", "pass123")
        assert result is False


class TestSendText:
    @pytest.mark.asyncio
    async def test_send_text_success(self, mock_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": 200, "data": {"guid": "msg-123"}}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        result = await send_text(
            mock_client, "http://bb:1234", "pass123",
            "iMessage;-;+15551234567", "Hello!",
            temp_guid="tg-1",
        )
        assert result is not None
        assert result["data"]["guid"] == "msg-123"

        # Verify the request
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "http://bb:1234/api/v1/message/text"
        assert call_kwargs[1]["json"]["chatGuid"] == "iMessage;-;+15551234567"
        assert call_kwargs[1]["json"]["message"] == "Hello!"
        assert call_kwargs[1]["json"]["tempGuid"] == "tg-1"

    @pytest.mark.asyncio
    async def test_send_text_generates_temp_guid(self, mock_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": 200}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        result = await send_text(
            mock_client, "http://bb:1234", "pass123",
            "iMessage;-;+15551234567", "Hello!",
        )
        assert result is not None
        # Verify a tempGuid was generated (UUID format)
        sent_json = mock_client.post.call_args[1]["json"]
        assert len(sent_json["tempGuid"]) == 36  # UUID string

    @pytest.mark.asyncio
    async def test_send_text_failure(self, mock_client):
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        result = await send_text(
            mock_client, "http://bb:1234", "pass123",
            "iMessage;-;+15551234567", "Hello!",
        )
        assert result is None


class TestSendAttachment:
    @pytest.mark.asyncio
    async def test_send_attachment_success(self, mock_client, tmp_path):
        test_file = tmp_path / "photo.jpg"
        test_file.write_bytes(b"fake image data")

        mock_response = MagicMock()
        mock_response.json.return_value = {"status": 200}
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        result = await send_attachment(
            mock_client, "http://bb:1234", "pass123",
            "iMessage;-;+15551234567", str(test_file), "photo.jpg",
            temp_guid="tg-att",
        )
        assert result is not None
        call_kwargs = mock_client.post.call_args
        assert "/api/v1/message/attachment" in call_kwargs[0][0]

    @pytest.mark.asyncio
    async def test_send_attachment_file_not_found(self, mock_client):
        result = await send_attachment(
            mock_client, "http://bb:1234", "pass123",
            "iMessage;-;+15551234567", "/nonexistent/file.jpg", "file.jpg",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_send_attachment_api_failure(self, mock_client, tmp_path):
        test_file = tmp_path / "doc.pdf"
        test_file.write_bytes(b"fake pdf")

        mock_client.post.side_effect = Exception("server error")
        result = await send_attachment(
            mock_client, "http://bb:1234", "pass123",
            "iMessage;-;+15551234567", str(test_file), "doc.pdf",
        )
        assert result is None


class TestQueryChats:
    @pytest.mark.asyncio
    async def test_query_chats_success(self, mock_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"guid": "iMessage;-;+15551234567", "displayName": "John"},
                {"guid": "iMessage;+;chat123", "displayName": "Group Chat"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_response

        result = await query_chats(mock_client, "http://bb:1234", "pass123", limit=10)
        assert len(result) == 2
        assert result[0]["guid"] == "iMessage;-;+15551234567"

    @pytest.mark.asyncio
    async def test_query_chats_failure(self, mock_client):
        mock_client.post.side_effect = Exception("timeout")
        result = await query_chats(mock_client, "http://bb:1234", "pass123")
        assert result == []


class TestGetChatMessages:
    @pytest.mark.asyncio
    async def test_get_chat_messages_success(self, mock_client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"guid": "msg-1", "text": "Hello", "isFromMe": False},
                {"guid": "msg-2", "text": "Hi!", "isFromMe": True},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        result = await get_chat_messages(
            mock_client, "http://bb:1234", "pass123",
            "iMessage;-;+15551234567", limit=10,
        )
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_chat_messages_failure(self, mock_client):
        mock_client.get.side_effect = Exception("timeout")
        result = await get_chat_messages(
            mock_client, "http://bb:1234", "pass123",
            "iMessage;-;+15551234567",
        )
        assert result == []
