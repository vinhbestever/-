import structlog
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.models.call_log import Utterance

logger = structlog.get_logger(__name__)


def _build_retry():
    return retry(
        stop=stop_after_attempt(settings.stt_max_retries),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True,
    )


class STTClient:
    """HTTP client for the external Speech-to-Text API."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(settings.stt_timeout_seconds),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def transcribe(self, audio_url: str, language: str = "vi") -> list[Utterance]:
        """
        Call the STT API and return parsed utterances.

        Expected STT API response format:
        {
          "utterances": [
            {"speaker": "A", "text": "...", "start_time": 0.0, "end_time": 1.5},
            {"speaker": "B", "text": "...", "start_time": 1.6, "end_time": 3.0}
          ]
        }
        """
        return await self._transcribe_with_retry(audio_url, language)

    async def _transcribe_with_retry(self, audio_url: str, language: str) -> list[Utterance]:
        retrier = _build_retry()

        @retrier
        async def _call():
            client = await self.get_client()
            logger.info("Calling STT API", audio_url=audio_url, language=language)
            resp = await client.post(
                settings.stt_api_url,
                json={"audio_url": audio_url, "language": language},
            )
            resp.raise_for_status()
            data = resp.json()
            utterances = [Utterance(**u) for u in data["utterances"]]
            logger.info("STT complete", audio_url=audio_url, utterance_count=len(utterances))
            return utterances

        return await _call()


stt_client = STTClient()
