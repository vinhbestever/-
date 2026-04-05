import pytest
from pydantic import ValidationError
from app.models.call_log import (
    CallLogCreate,
    CallDirection,
    CallStatus,
    Speaker,
    Utterance,
    SemanticSearchRequest,
)


class TestCallLogCreate:
    def test_valid_minimal(self):
        log = CallLogCreate(
            utterances=[Utterance(speaker="A", text="Xin chào")]
        )
        assert log.call_id is not None
        assert log.direction == CallDirection.INBOUND
        assert len(log.utterances) == 1

    def test_valid_full(self):
        log = CallLogCreate(
            direction=CallDirection.OUTBOUND,
            status=CallStatus.COMPLETED,
            speaker_a=Speaker(name="Agent", phone_number="0901234567", role="agent"),
            speaker_b=Speaker(name="Customer", phone_number="0987654321", role="customer"),
            utterances=[
                Utterance(speaker="Agent", text="Xin chào anh", start_time=0.0, end_time=1.5),
                Utterance(speaker="Customer", text="Chào bạn", start_time=1.6, end_time=2.8),
            ],
            language="vi",
            tags=["support", "vip"],
        )
        assert log.speaker_a.name == "Agent"
        assert log.language == "vi"
        assert len(log.utterances) == 2
        assert len(log.tags) == 2

    def test_empty_utterances_rejected(self):
        with pytest.raises(ValidationError):
            CallLogCreate(utterances=[])


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
