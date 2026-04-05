import asyncio
from fastapi import APIRouter, HTTPException, Query

from app.models.call_log import (
    CallLogResponse,
    IngestRequest,
    IngestJobResponse,
    IngestJobDetail,
    SemanticSearchRequest,
    SearchResult,
    JobStatus,
)
from app.services.elasticsearch_service import es_service
from app.services.embedding_service import embedding_service
from app.services.ingest_queue import ingest_queue, QueueFullError

router = APIRouter()


async def _embed_async(text: str) -> list[float]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, embedding_service.embed, text)


# ── Ingest (submit audio → background STT → embed → store) ───


@router.post("/ingest", response_model=IngestJobResponse, status_code=202)
async def submit_ingest(req: IngestRequest):
    """
    Submit a call for async processing.
    Returns immediately with a job_id. Returns 429 if the queue is full.
    """
    try:
        job = ingest_queue.submit(req)
    except QueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    return IngestJobResponse(
        job_id=job.job_id,
        call_id=job.call_id,
        status=job.status,
        message=f"Queued for processing (position ~{job.queue_position})",
    )


@router.get("/ingest/{job_id}", response_model=IngestJobDetail)
async def get_ingest_status(job_id: str):
    """Check the status of an async ingest job."""
    job = ingest_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/ingest", response_model=dict)
async def get_queue_stats():
    """Overview of the ingest queue."""
    jobs = ingest_queue.jobs
    return {
        "queue_pending": ingest_queue.pending_count,
        "total_jobs": len(jobs),
        "by_status": {
            s.value: sum(1 for j in jobs.values() if j.status == s)
            for s in JobStatus
        },
    }


# ── Read ──────────────────────────────────────────────────────


@router.get("/call-logs", response_model=SearchResult)
async def list_call_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """List call logs ordered by most recent."""
    return await es_service.list_logs(page=page, size=size)


@router.get("/call-logs/{call_id}", response_model=CallLogResponse)
async def get_call_log(call_id: str):
    """Retrieve a single call log by ID."""
    doc = await es_service.get_call_log(call_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Call log not found")
    return CallLogResponse(
        call_id=doc.call_id,
        direction=doc.direction,
        status=doc.status,
        speaker_a=doc.speaker_a,
        speaker_b=doc.speaker_b,
        utterances=doc.utterances,
        full_text=doc.full_text,
        call_start_time=doc.call_start_time,
        call_end_time=doc.call_end_time,
        duration_seconds=doc.duration_seconds,
        language=doc.language,
        tags=doc.tags,
        indexed_at=doc.indexed_at,
    )


# ── Search ────────────────────────────────────────────────────


@router.post("/search/semantic", response_model=SearchResult)
async def semantic_search(req: SemanticSearchRequest):
    """Pure semantic (vector) search — find calls by meaning."""
    query_vector = await _embed_async(req.query)
    return await es_service.semantic_search(query_vector, req)


@router.post("/search/hybrid", response_model=SearchResult)
async def hybrid_search(req: SemanticSearchRequest):
    """Hybrid search — combines vector similarity with BM25 full-text."""
    query_vector = await _embed_async(req.query)
    return await es_service.hybrid_search(req.query, query_vector, req)
