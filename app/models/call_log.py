from datetime import datetime
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field
import uuid


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    INTERNAL = "internal"


class CallStatus(str, Enum):
    COMPLETED = "completed"
    MISSED = "missed"
    FAILED = "failed"
    ONGOING = "ongoing"


class Participant(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None  # e.g. "agent", "customer", "supervisor"


class TranscriptSegment(BaseModel):
    speaker: str
    text: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    confidence: Optional[float] = None


class CallLogCreate(BaseModel):
    """Payload for creating a new call log entry."""
    call_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    direction: CallDirection = CallDirection.INBOUND
    status: CallStatus = CallStatus.COMPLETED
    caller: Optional[Participant] = None
    callee: Optional[Participant] = None
    participants: list[Participant] = Field(default_factory=list)
    transcript_text: str = Field(..., min_length=1, description="Full transcript text of the call")
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    call_start_time: Optional[datetime] = None
    call_end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    language: str = "vi"
    source_system: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class EnrichedData(BaseModel):
    """Data extracted by the NLP enrichment pipeline."""
    summary: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    topics: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    phone_numbers_mentioned: list[str] = Field(default_factory=list)
    dates_mentioned: list[str] = Field(default_factory=list)
    amounts_mentioned: list[str] = Field(default_factory=list)


class CallLogDocument(BaseModel):
    """Full document stored in Elasticsearch."""
    call_id: str
    direction: CallDirection
    status: CallStatus
    caller: Optional[Participant] = None
    callee: Optional[Participant] = None
    participants: list[Participant] = Field(default_factory=list)
    transcript_text: str
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    call_start_time: Optional[datetime] = None
    call_end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    language: str = "vi"
    source_system: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    enriched: Optional[EnrichedData] = None
    indexed_at: datetime = Field(default_factory=datetime.utcnow)
    enriched_at: Optional[datetime] = None


class CallLogResponse(BaseModel):
    call_id: str
    direction: CallDirection
    status: CallStatus
    caller: Optional[Participant] = None
    callee: Optional[Participant] = None
    transcript_text: str
    call_start_time: Optional[datetime] = None
    call_end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    language: str
    tags: list[str]
    enriched: Optional[EnrichedData] = None
    indexed_at: datetime


class SearchQuery(BaseModel):
    """Smart search query model."""
    q: Optional[str] = None
    call_id: Optional[str] = None
    direction: Optional[CallDirection] = None
    status: Optional[CallStatus] = None
    caller_phone: Optional[str] = None
    callee_phone: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    duration_min: Optional[float] = None
    duration_max: Optional[float] = None
    language: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    source_system: Optional[str] = None
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    sort_by: str = "indexed_at"
    sort_order: str = "desc"


class SearchResult(BaseModel):
    total: int
    page: int
    size: int
    results: list[CallLogResponse]
    aggregations: Optional[dict] = None
