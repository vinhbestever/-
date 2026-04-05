from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.models.call_log import (
    CallLogCreate,
    CallLogDocument,
    CallLogResponse,
    SearchQuery,
    SearchResult,
)
from app.services.elasticsearch_service import es_service
from app.services.kafka_service import kafka_producer
from app.services.enrichment_service import enrichment_service
from app.config import settings

router = APIRouter()


@router.post("/call-logs", response_model=CallLogResponse, status_code=201)
async def create_call_log(payload: CallLogCreate):
    """
    Ingest a new call log. The transcript is immediately indexed into
    Elasticsearch and published to Kafka for async enrichment.
    """
    doc = CallLogDocument(
        call_id=payload.call_id,
        direction=payload.direction,
        status=payload.status,
        caller=payload.caller,
        callee=payload.callee,
        participants=payload.participants,
        transcript_text=payload.transcript_text,
        transcript_segments=payload.transcript_segments,
        call_start_time=payload.call_start_time,
        call_end_time=payload.call_end_time,
        duration_seconds=payload.duration_seconds,
        language=payload.language,
        source_system=payload.source_system,
        tags=payload.tags,
        metadata=payload.metadata,
    )

    if settings.enrichment_enabled:
        enriched = enrichment_service.enrich(doc.transcript_text, doc.language)
        doc.enriched = enriched
        doc.enriched_at = datetime.utcnow()

    await es_service.index_call_log(doc)

    try:
        await kafka_producer.send_raw_call_log(
            call_id=doc.call_id,
            data=doc.model_dump(mode="json"),
        )
    except Exception:
        pass

    return CallLogResponse(
        call_id=doc.call_id,
        direction=doc.direction,
        status=doc.status,
        caller=doc.caller,
        callee=doc.callee,
        transcript_text=doc.transcript_text,
        call_start_time=doc.call_start_time,
        call_end_time=doc.call_end_time,
        duration_seconds=doc.duration_seconds,
        language=doc.language,
        tags=doc.tags,
        enriched=doc.enriched,
        indexed_at=doc.indexed_at,
    )


@router.get("/call-logs/{call_id}", response_model=CallLogResponse)
async def get_call_log(call_id: str):
    """Retrieve a single call log by its ID."""
    doc = await es_service.get_call_log(call_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Call log not found")
    return CallLogResponse(
        call_id=doc.call_id,
        direction=doc.direction,
        status=doc.status,
        caller=doc.caller,
        callee=doc.callee,
        transcript_text=doc.transcript_text,
        call_start_time=doc.call_start_time,
        call_end_time=doc.call_end_time,
        duration_seconds=doc.duration_seconds,
        language=doc.language,
        tags=doc.tags,
        enriched=doc.enriched,
        indexed_at=doc.indexed_at,
    )


@router.post("/call-logs/search", response_model=SearchResult)
async def search_call_logs(query: SearchQuery):
    """
    Advanced search with filters, full-text search, and aggregations.
    """
    return await es_service.search(query)


@router.get("/call-logs/smart-search/", response_model=SearchResult)
async def smart_search(
    q: str = Query(..., min_length=1, description="Search text"),
    size: int = Query(20, ge=1, le=100),
):
    """
    Intelligent search: automatically matches against transcript text,
    phone numbers, keywords, topics, summaries, and participant names.
    Returns results ranked by relevance with aggregated analytics.
    """
    return await es_service.smart_search(q, size)


@router.get("/analytics")
async def get_analytics(
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
):
    """Get aggregated analytics across all call logs."""
    return await es_service.get_analytics(date_from, date_to)


@router.post("/call-logs/{call_id}/re-enrich", response_model=CallLogResponse)
async def re_enrich_call_log(call_id: str):
    """Re-run the enrichment pipeline on an existing call log."""
    doc = await es_service.get_call_log(call_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Call log not found")

    enriched = enrichment_service.enrich(doc.transcript_text, doc.language)
    await es_service.update_enrichment(call_id, enriched)
    doc.enriched = enriched

    return CallLogResponse(
        call_id=doc.call_id,
        direction=doc.direction,
        status=doc.status,
        caller=doc.caller,
        callee=doc.callee,
        transcript_text=doc.transcript_text,
        call_start_time=doc.call_start_time,
        call_end_time=doc.call_end_time,
        duration_seconds=doc.duration_seconds,
        language=doc.language,
        tags=doc.tags,
        enriched=enriched,
        indexed_at=doc.indexed_at,
    )
