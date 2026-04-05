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


class JobStatus(str, Enum):
    QUEUED = "queued"
    CALLING_STT = "calling_stt"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    DONE = "done"
    FAILED = "failed"


class Speaker(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None


class Utterance(BaseModel):
    """A single turn in the conversation, segmented by the STT API."""
    speaker: str
    text: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None


# ── Ingest request ────────────────────────────────────────────


class IngestRequest(BaseModel):
    """Submit a call for async processing: STT → embed → store."""
    call_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    audio_url: str = Field(..., min_length=1)
    direction: CallDirection = CallDirection.INBOUND
    status: CallStatus = CallStatus.COMPLETED
    speaker_a: Optional[Speaker] = None
    speaker_b: Optional[Speaker] = None
    call_start_time: Optional[datetime] = None
    call_end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    language: str = "vi"
    source_system: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class IngestJobResponse(BaseModel):
    job_id: str
    call_id: str
    status: JobStatus
    message: str


class IngestJobDetail(BaseModel):
    job_id: str
    call_id: str
    status: JobStatus
    error: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    queue_position: Optional[int] = None


# ── Elasticsearch document ────────────────────────────────────


class CallLogDocument(BaseModel):
    """Full document stored in Elasticsearch."""
    call_id: str
    direction: CallDirection
    status: CallStatus
    speaker_a: Optional[Speaker] = None
    speaker_b: Optional[Speaker] = None
    utterances: list[Utterance]
    full_text: str
    call_start_time: Optional[datetime] = None
    call_end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    language: str = "vi"
    source_system: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    embedding: list[float] = Field(default_factory=list)
    indexed_at: datetime = Field(default_factory=datetime.utcnow)


# ── Response / search models ─────────────────────────────────


class CallLogResponse(BaseModel):
    call_id: str
    direction: CallDirection
    status: CallStatus
    speaker_a: Optional[Speaker] = None
    speaker_b: Optional[Speaker] = None
    utterances: list[Utterance]
    full_text: str
    call_start_time: Optional[datetime] = None
    call_end_time: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    language: str
    tags: list[str]
    indexed_at: datetime
    score: Optional[float] = None


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    size: int = Field(default=20, ge=1, le=100)
    min_score: Optional[float] = None
    direction: Optional[CallDirection] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    tags: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    total: int
    results: list[CallLogResponse]
