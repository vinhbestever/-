import pytest
from unittest.mock import AsyncMock, patch
import httpx

from app.services.stt_client import STTClient
from app.models.call_log import Utterance


class TestSTTClient:
    @pytest.mark.asyncio
    async def test_transcribe_parses_response(self):
        mock_request = httpx.Request("POST", "http://localhost:8001/transcribe")
        mock_response = httpx.Response(
            200,
            json={
                "utterances": [
                    {"speaker": "A", "text": "Xin chào", "start_time": 0.0, "end_time": 1.5},
                    {"speaker": "B", "text": "Chào bạn", "start_time": 1.6, "end_time": 3.0},
                ]
            },
            request=mock_request,
        )

        client = STTClient()
        with patch.object(client, "get_client") as mock_get:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http

            result = await client.transcribe("https://example.com/audio.wav", "vi")

        assert len(result) == 2
        assert isinstance(result[0], Utterance)
        assert result[0].speaker == "A"
        assert result[0].text == "Xin chào"
        assert result[1].speaker == "B"
