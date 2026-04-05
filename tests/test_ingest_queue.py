import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from app.models.call_log import (
    IngestRequest,
    JobStatus,
    Utterance,
    Speaker,
)
from app.services.ingest_queue import IngestQueue, QueueFullError


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
    return (
        patch("app.services.ingest_queue.stt_client"),
        patch("app.services.ingest_queue.embedding_service"),
        patch("app.services.ingest_queue.es_service"),
    )


def _make_mock_stt(mock_stt, transcribe_fn):
    mock_stt.transcribe = transcribe_fn
    mock_stt.close = AsyncMock()
    return mock_stt


class TestSubmit:
    @pytest.mark.asyncio
    async def test_returns_queued_job(self, queue, sample_request):
        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2, p3:
            _make_mock_stt(mock_stt, AsyncMock(return_value=[]))
            await queue.start()
            job = queue.submit(sample_request)
            assert job.status == JobStatus.QUEUED
            assert job.call_id == sample_request.call_id
            assert job.created_at is not None
            await queue.stop()

    @pytest.mark.asyncio
    async def test_rejects_when_queue_full(self):
        """Queue with maxsize=2 should raise QueueFullError on 3rd submit."""
        q = IngestQueue()
        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2, p3:
            mock_stt.close = AsyncMock()
            # Use a tiny queue and no workers so items stay in queue
            with patch("app.services.ingest_queue.settings") as mock_settings:
                mock_settings.ingest_queue_max_size = 2
                mock_settings.stt_max_concurrency = 1
                mock_settings.ingest_worker_count = 0  # no workers → items stay queued
                await q.start()

            req1 = IngestRequest(audio_url="https://example.com/1.wav")
            req2 = IngestRequest(audio_url="https://example.com/2.wav")
            req3 = IngestRequest(audio_url="https://example.com/3.wav")

            q.submit(req1)
            q.submit(req2)
            with pytest.raises(QueueFullError):
                q.submit(req3)

            await q.stop()


class TestJobLookup:
    def test_returns_none_for_unknown(self, queue):
        assert queue.get_job("nonexistent") is None

    @pytest.mark.asyncio
    async def test_returns_submitted_job(self, queue, sample_request):
        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2, p3:
            _make_mock_stt(mock_stt, AsyncMock(return_value=[]))
            await queue.start()
            job = queue.submit(sample_request)
            found = queue.get_job(job.job_id)
            assert found is not None
            assert found.job_id == job.job_id
            await queue.stop()


class TestProcessing:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, queue, sample_request):
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
            job = queue.submit(sample_request)

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
            job = queue.submit(sample_request)

            for _ in range(50):
                await asyncio.sleep(0.1)
                if queue.get_job(job.job_id).status in (JobStatus.DONE, JobStatus.FAILED):
                    break

            final = queue.get_job(job.job_id)
            assert final.status == JobStatus.FAILED
            assert "STT API timeout" in final.error

            await queue.stop()

    @pytest.mark.asyncio
    async def test_concurrent_processing(self, queue):
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
                jobs.append(queue.submit(req))

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
            time_span = max(starts) - min(starts)
            assert time_span < 0.15

            await queue.stop()


class TestCleanup:
    @pytest.mark.asyncio
    async def test_purge_expired_jobs(self, queue):
        """Manually call _purge_expired_jobs to verify old done jobs are removed."""
        p1, p2, p3 = _patch_services()
        with p1 as mock_stt, p2, p3:
            mock_stt.close = AsyncMock()
            await queue.start()

            from app.models.call_log import IngestJobDetail
            old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)

            queue._jobs["old-done"] = IngestJobDetail(
                job_id="old-done",
                call_id="old-done",
                status=JobStatus.DONE,
                created_at=old_time,
                completed_at=old_time,
            )
            queue._jobs["old-failed"] = IngestJobDetail(
                job_id="old-failed",
                call_id="old-failed",
                status=JobStatus.FAILED,
                error="test",
                created_at=old_time,
                completed_at=old_time,
            )
            queue._jobs["still-queued"] = IngestJobDetail(
                job_id="still-queued",
                call_id="still-queued",
                status=JobStatus.QUEUED,
                created_at=old_time,
            )

            queue._purge_expired_jobs()

            assert "old-done" not in queue._jobs
            assert "old-failed" not in queue._jobs
            assert "still-queued" in queue._jobs

            await queue.stop()
