import asyncio
import time
import structlog
from datetime import datetime, timezone
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
from app.middleware import (
    INGEST_QUEUE_DEPTH,
    INGEST_JOBS_TOTAL,
    STT_CALL_DURATION,
    EMBED_DURATION,
)

logger = structlog.get_logger(__name__)

_JOB_TTL_SECONDS = 3600


class IngestQueue:
    """
    In-process async job queue with bounded concurrency.

    Handles high load via:
    - Bounded asyncio.Queue with non-blocking reject when full
    - asyncio.Semaphore to cap concurrent STT API calls
    - run_in_executor for CPU-bound embedding (avoids blocking the event loop)
    - TTL-based auto-cleanup of finished jobs to prevent memory leak
    - Graceful shutdown: waits for in-flight jobs to finish before stopping
    """

    def __init__(self):
        self._queue: asyncio.Queue | None = None
        self._jobs: dict[str, IngestJobDetail] = {}
        self._workers: list[asyncio.Task] = []
        self._semaphore: asyncio.Semaphore | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._running = False
        self._in_flight = 0

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

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info(
            "Ingest queue started",
            workers=settings.ingest_worker_count,
            stt_concurrency=settings.stt_max_concurrency,
            max_queue=settings.ingest_queue_max_size,
        )

    async def stop(self):
        self._running = False

        # Drain: wait for in-flight jobs to finish (up to 30s)
        for _ in range(300):
            if self._in_flight == 0 and self.pending_count == 0:
                break
            await asyncio.sleep(0.1)

        if self._cleanup_task:
            self._cleanup_task.cancel()
        for worker in self._workers:
            worker.cancel()
        tasks = self._workers + ([self._cleanup_task] if self._cleanup_task else [])
        await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()
        self._cleanup_task = None
        await stt_client.close()
        logger.info("Ingest queue stopped", drained_ok=self._in_flight == 0)

    def submit(self, req: IngestRequest) -> IngestJobDetail:
        """
        Non-blocking submit. Raises QueueFullError immediately if queue is at
        capacity instead of hanging the API request.
        """
        job = IngestJobDetail(
            job_id=req.call_id,
            call_id=req.call_id,
            status=JobStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )

        try:
            self._queue.put_nowait((job.job_id, req))
        except asyncio.QueueFull:
            raise QueueFullError(
                f"Ingest queue is full ({settings.ingest_queue_max_size} pending). "
                "Try again later."
            )

        self._jobs[job.job_id] = job
        job.queue_position = self._queue.qsize()
        INGEST_QUEUE_DEPTH.set(self._queue.qsize())

        logger.info("Job queued", job_id=job.job_id, queue_size=self._queue.qsize())
        return job

    def get_job(self, job_id: str) -> Optional[IngestJobDetail]:
        return self._jobs.get(job_id)

    # ── Workers ───────────────────────────────────────────────

    async def _worker_loop(self, worker_id: int):
        logger.info("Worker started", worker_id=worker_id)
        while self._running:
            try:
                job_id, req = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            self._in_flight += 1
            INGEST_QUEUE_DEPTH.set(self._queue.qsize())
            try:
                await self._process_job(job_id, req)
            except Exception:
                logger.exception("Unhandled error in worker", worker_id=worker_id, job_id=job_id)
            finally:
                self._in_flight -= 1
                self._queue.task_done()

    async def _process_job(self, job_id: str, req: IngestRequest):
        job = self._jobs[job_id]

        try:
            # Step 1: Call STT API (rate-limited by semaphore)
            job.status = JobStatus.CALLING_STT
            t0 = time.perf_counter()
            async with self._semaphore:
                utterances = await stt_client.transcribe(req.audio_url, req.language)
            STT_CALL_DURATION.observe(time.perf_counter() - t0)

            # Step 2: Embed in thread pool
            job.status = JobStatus.EMBEDDING
            full_text = "\n".join(f"{u.speaker}: {u.text}" for u in utterances)
            t0 = time.perf_counter()
            loop = asyncio.get_running_loop()
            vector = await loop.run_in_executor(None, embedding_service.embed, full_text)
            EMBED_DURATION.observe(time.perf_counter() - t0)

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
            job.completed_at = datetime.now(timezone.utc)
            INGEST_JOBS_TOTAL.labels(status="done").inc()
            logger.info("Job completed", job_id=job_id, call_id=req.call_id)

        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            INGEST_JOBS_TOTAL.labels(status="failed").inc()
            logger.error("Job failed", job_id=job_id, error=str(exc))

    # ── Cleanup ───────────────────────────────────────────────

    async def _cleanup_loop(self):
        while self._running:
            try:
                await asyncio.sleep(60)
                self._purge_expired_jobs()
            except asyncio.CancelledError:
                break

    def _purge_expired_jobs(self):
        now = datetime.now(timezone.utc)
        expired = [
            jid
            for jid, job in self._jobs.items()
            if job.status in (JobStatus.DONE, JobStatus.FAILED)
            and job.completed_at
            and (now - job.completed_at.replace(tzinfo=timezone.utc)).total_seconds() > _JOB_TTL_SECONDS
        ]
        for jid in expired:
            del self._jobs[jid]
        if expired:
            logger.info("Purged expired jobs", count=len(expired))


class QueueFullError(Exception):
    pass


ingest_queue = IngestQueue()
