import pytest
from pydantic import ValidationError
from app.models.call_log import (
    CallLogCreate,
    CallDirection,
    CallStatus,
    Participant,
    SearchQuery,
)


class TestCallLogCreate:
    def test_valid_minimal(self):
        log = CallLogCreate(transcript_text="Hello world")
        assert log.call_id is not None
        assert log.direction == CallDirection.INBOUND
        assert log.transcript_text == "Hello world"

    def test_valid_full(self):
        log = CallLogCreate(
            direction=CallDirection.OUTBOUND,
            status=CallStatus.COMPLETED,
            caller=Participant(name="Agent", phone_number="0901234567", role="agent"),
            callee=Participant(name="Customer", phone_number="0987654321", role="customer"),
            transcript_text="Xin chào, tôi muốn hỏi về dịch vụ",
            language="vi",
            tags=["support", "vip"],
        )
        assert log.caller.name == "Agent"
        assert log.language == "vi"
        assert len(log.tags) == 2

    def test_empty_transcript_rejected(self):
        with pytest.raises(ValidationError):
            CallLogCreate(transcript_text="")


class TestSearchQuery:
    def test_defaults(self):
        q = SearchQuery()
        assert q.page == 1
        assert q.size == 20
        assert q.sort_by == "indexed_at"

    def test_custom_values(self):
        q = SearchQuery(
            q="khiếu nại",
            direction=CallDirection.INBOUND,
            tags=["vip"],
            page=2,
            size=50,
        )
        assert q.q == "khiếu nại"
        assert q.direction == CallDirection.INBOUND
        assert q.page == 2
