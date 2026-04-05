import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from app.models.call_log import (
    IngestRequest,
    JobStatus,
    Utterance,
    Speaker,
)
from app.services.ingest_queue import IngestQueue


@pytest.fixture
def queue():
    return IngestQueue()


@pytest.fixture
def sample_request():
    return IngestRequest(
        audio_url="https://storage.example.com/calls/abc123.wav",
        direction="inbound",
        speaker_a=Speaker(name="Agent", role="agent"),
        speaker_b=Speaker(name="Customer", role="customer"),
        language="vi",
        tags=["support"],
    )


def _patch_services():
    """Context manager that patches stt_client, embedding_service, es_service."""
    return (
        patch("app.services.ingest_queue.stt_client"),
        patch("app.services.ingest_queue.embedding_service"),
        patch("app.services.ingest_queue.es_service"),
    )


def _make_mock_stt(mock_stt, transcribe_fn):
    mock_stt.transcribe = transcribe_fn
    mock_stt.close = AsyncMock()
    return mock_stt


class TestIngestQueue:
    @pytest.mark.asyncio
    async def test_submit_returns_queued_job(self, queue, sample_request):
        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2, p3:
            _make_mock_stt(mock_stt, AsyncMock(return_value=[]))
            await queue.start()
            job = await queue.submit(sample_request)
            assert job.status == JobStatus.QUEUED
            assert job.call_id == sample_request.call_id
            assert job.job_id == sample_request.call_id
            assert job.created_at is not None
            await queue.stop()

    @pytest.mark.asyncio
    async def test_get_job_returns_none_for_unknown(self, queue):
        assert queue.get_job("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_job_returns_submitted_job(self, queue, sample_request):
        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2, p3:
            _make_mock_stt(mock_stt, AsyncMock(return_value=[]))
            await queue.start()
            job = await queue.submit(sample_request)
            found = queue.get_job(job.job_id)
            assert found is not None
            assert found.job_id == job.job_id
            await queue.stop()

    @pytest.mark.asyncio
    async def test_pending_count(self, queue):
        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2, p3:
            mock_stt.close = AsyncMock()
            await queue.start()
            assert queue.pending_count >= 0
            await queue.stop()

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock_stt(self, queue, sample_request):
        mock_utterances = [
            Utterance(speaker="Agent", text="Xin chào"),
            Utterance(speaker="Customer", text="Chào bạn"),
        ]

        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2 as mock_embed, p3 as mock_es:
            _make_mock_stt(mock_stt, AsyncMock(return_value=mock_utterances))
            mock_embed.embed = MagicMock(return_value=[0.1] * 384)
            mock_es.index_call_log = AsyncMock(return_value="test-id")

            await queue.start()
            job = await queue.submit(sample_request)

            for _ in range(50):
                await asyncio.sleep(0.1)
                if queue.get_job(job.job_id).status in (JobStatus.DONE, JobStatus.FAILED):
                    break

            final = queue.get_job(job.job_id)
            assert final.status == JobStatus.DONE
            assert final.completed_at is not None

            mock_stt.transcribe.assert_called_once_with(
                sample_request.audio_url, sample_request.language
            )
            mock_embed.embed.assert_called_once()
            mock_es.index_call_log.assert_called_once()

            await queue.stop()

    @pytest.mark.asyncio
    async def test_failed_stt_marks_job_failed(self, queue, sample_request):
        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2, p3:
            _make_mock_stt(mock_stt, AsyncMock(side_effect=Exception("STT API timeout")))

            await queue.start()
            job = await queue.submit(sample_request)

            for _ in range(50):
                await asyncio.sleep(0.1)
                if queue.get_job(job.job_id).status in (JobStatus.DONE, JobStatus.FAILED):
                    break

            final = queue.get_job(job.job_id)
            assert final.status == JobStatus.FAILED
            assert "STT API timeout" in final.error

            await queue.stop()

    @pytest.mark.asyncio
    async def test_multiple_jobs_processed_concurrently(self, queue):
        call_log = []

        async def slow_stt(audio_url, language):
            call_log.append(("start", audio_url, asyncio.get_event_loop().time()))
            await asyncio.sleep(0.2)
            call_log.append(("end", audio_url, asyncio.get_event_loop().time()))
            return [Utterance(speaker="A", text="hello")]

        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2 as mock_embed, p3 as mock_es:
            _make_mock_stt(mock_stt, slow_stt)
            mock_embed.embed = MagicMock(return_value=[0.1] * 384)
            mock_es.index_call_log = AsyncMock(return_value="ok")

            await queue.start()

            jobs = []
            for i in range(3):
                req = IngestRequest(audio_url=f"https://example.com/{i}.wav")
                jobs.append(await queue.submit(req))

            for _ in range(100):
                await asyncio.sleep(0.1)
                if all(
                    queue.get_job(j.job_id).status in (JobStatus.DONE, JobStatus.FAILED)
                    for j in jobs
                ):
                    break

            assert all(queue.get_job(j.job_id).status == JobStatus.DONE for j in jobs)

            starts = [t for label, _, t in call_log if label == "start"]
            assert len(starts) == 3
            # With 3 workers, all 3 STT calls should overlap in time
            time_span = max(starts) - min(starts)
            assert time_span < 0.15

            await queue.stop()
