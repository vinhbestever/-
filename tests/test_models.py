import pytest
from pydantic import ValidationError
from app.models.call_log import (
    IngestRequest,
    CallDirection,
    Speaker,
    SemanticSearchRequest,
)


class TestIngestRequest:
    def test_valid_minimal(self):
        req = IngestRequest(audio_url="https://example.com/call.wav")
        assert req.call_id is not None
        assert req.audio_url == "https://example.com/call.wav"
        assert req.direction == CallDirection.INBOUND

    def test_valid_full(self):
        req = IngestRequest(
            audio_url="https://example.com/call.wav",
            direction=CallDirection.OUTBOUND,
            speaker_a=Speaker(name="Agent", phone_number="0901234567", role="agent"),
            speaker_b=Speaker(name="Customer", phone_number="0987654321", role="customer"),
            language="vi",
            tags=["support", "vip"],
        )
        assert req.speaker_a.name == "Agent"
        assert len(req.tags) == 2

    def test_empty_audio_url_rejected(self):
        with pytest.raises(ValidationError):
            IngestRequest(audio_url="")


class TestSemanticSearchRequest:
    def test_defaults(self):
        req = SemanticSearchRequest(query="tìm cuộc gọi khiếu nại")
        assert req.size == 20
        assert req.min_score is None
        assert req.direction is None

    def test_with_filters(self):
        req = SemanticSearchRequest(
            query="thanh toán",
            size=10,
            direction=CallDirection.INBOUND,
            tags=["payment"],
        )
        assert req.size == 10
        assert req.direction == CallDirection.INBOUND

    def test_empty_query_rejected(self):
        with pytest.raises(ValidationError):
            SemanticSearchRequest(query="")
