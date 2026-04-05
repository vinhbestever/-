import asyncio
import structlog
from datetime import datetime
from typing import Optional

from app.config import settings
from app.models.call_log import (
    IngestRequest,
    IngestJobDetail,
    CallLogDocument,
    JobStatus,
)
from app.services.stt_client import stt_client
from app.services.embedding_service import embedding_service
from app.services.elasticsearch_service import es_service

logger = structlog.get_logger(__name__)


class IngestQueue:
    """
    In-process async job queue with bounded concurrency.

    - asyncio.Queue holds pending jobs
    - N workers consume from the queue concurrently
    - asyncio.Semaphore caps concurrent STT API calls
    - Job status tracked in-memory dict (swap for Redis if multi-instance)
    """

    def __init__(self):
        self._queue: asyncio.Queue | None = None
        self._jobs: dict[str, IngestJobDetail] = {}
        self._workers: list[asyncio.Task] = []
        self._semaphore: asyncio.Semaphore | None = None
        self._running = False

    @property
    def jobs(self) -> dict[str, IngestJobDetail]:
        return self._jobs

    @property
    def pending_count(self) -> int:
        return self._queue.qsize() if self._queue else 0

    async def start(self):
        self._queue = asyncio.Queue(maxsize=settings.ingest_queue_max_size)
        self._semaphore = asyncio.Semaphore(settings.stt_max_concurrency)
        self._running = True

        for i in range(settings.ingest_worker_count):
            task = asyncio.create_task(self._worker_loop(i))
            self._workers.append(task)

        logger.info(
            "Ingest queue started",
            workers=settings.ingest_worker_count,
            stt_concurrency=settings.stt_max_concurrency,
            max_queue=settings.ingest_queue_max_size,
        )

    async def stop(self):
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        await stt_client.close()
        logger.info("Ingest queue stopped")

    async def submit(self, req: IngestRequest) -> IngestJobDetail:
        job = IngestJobDetail(
            job_id=req.call_id,
            call_id=req.call_id,
            status=JobStatus.QUEUED,
            created_at=datetime.utcnow(),
        )
        self._jobs[job.job_id] = job

        await self._queue.put((job.job_id, req))
        job.queue_position = self._queue.qsize()

        logger.info("Job queued", job_id=job.job_id, queue_size=self._queue.qsize())
        return job

    def get_job(self, job_id: str) -> Optional[IngestJobDetail]:
        return self._jobs.get(job_id)

    async def _worker_loop(self, worker_id: int):
        logger.info("Worker started", worker_id=worker_id)
        while self._running:
            try:
                job_id, req = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._process_job(job_id, req)
            except Exception:
                logger.exception("Unhandled error in worker", worker_id=worker_id, job_id=job_id)
            finally:
                self._queue.task_done()

    async def _process_job(self, job_id: str, req: IngestRequest):
        job = self._jobs[job_id]

        try:
            # Step 1: Call STT API (rate-limited by semaphore)
            job.status = JobStatus.CALLING_STT
            async with self._semaphore:
                utterances = await stt_client.transcribe(req.audio_url, req.language)

            # Step 2: Embed
            job.status = JobStatus.EMBEDDING
            full_text = "\n".join(f"{u.speaker}: {u.text}" for u in utterances)
            vector = embedding_service.embed(full_text)

            # Step 3: Index into Elasticsearch
            job.status = JobStatus.INDEXING
            doc = CallLogDocument(
                call_id=req.call_id,
                direction=req.direction,
                status=req.status,
                speaker_a=req.speaker_a,
                speaker_b=req.speaker_b,
                utterances=utterances,
                full_text=full_text,
                call_start_time=req.call_start_time,
                call_end_time=req.call_end_time,
                duration_seconds=req.duration_seconds,
                language=req.language,
                source_system=req.source_system,
                tags=req.tags,
                metadata=req.metadata,
                embedding=vector,
            )
            await es_service.index_call_log(doc)

            job.status = JobStatus.DONE
            job.completed_at = datetime.utcnow()
            logger.info("Job completed", job_id=job_id, call_id=req.call_id)

        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.utcnow()
            logger.error("Job failed", job_id=job_id, error=str(exc))


ingest_queue = IngestQueue()
