import pytest
from app.services.enrichment_service import EnrichmentService


@pytest.fixture
def service():
    return EnrichmentService()


class TestPhoneExtraction:
    def test_extracts_vn_phone_numbers(self, service):
        text = "Xin gọi lại số 0912345678 hoặc +84 987 654 321 nhé"
        result = service._extract_phone_numbers(text)
        assert len(result) >= 1

    def test_no_phone_numbers(self, service):
        text = "Không có số điện thoại trong đoạn này"
        result = service._extract_phone_numbers(text)
        assert result == []


class TestAmountExtraction:
    def test_extracts_vnd_amounts(self, service):
        text = "Tổng số tiền là 500.000 đồng và phí ship 30.000 VND"
        result = service._extract_amounts(text)
        assert len(result) >= 1

    def test_extracts_usd(self, service):
        text = "The total is $500 USD"
        result = service._extract_amounts(text)
        assert len(result) >= 1


class TestDateExtraction:
    def test_extracts_date_format(self, service):
        text = "Hẹn ngày 15/03/2026 lúc 9h sáng"
        result = service._extract_dates(text)
        assert len(result) >= 1


class TestActionItems:
    def test_extracts_action_items_vi(self, service):
        text = "Tôi sẽ gọi lại vào ngày mai. Bạn cần kiểm tra lại đơn hàng."
        result = service._extract_action_items(text)
        assert len(result) >= 1

    def test_extracts_action_items_en(self, service):
        text = "I will follow up tomorrow. We need to check the order status."
        result = service._extract_action_items(text)
        assert len(result) >= 1


class TestSentiment:
    def test_positive_sentiment(self, service):
        text = "Cảm ơn bạn rất nhiều, dịch vụ tuyệt vời, tôi rất hài lòng"
        sentiment, score = service._analyze_sentiment(text)
        assert sentiment == "positive"
        assert score > 0

    def test_negative_sentiment(self, service):
        text = "Dịch vụ quá tệ, tôi rất thất vọng và muốn khiếu nại"
        sentiment, score = service._analyze_sentiment(text)
        assert sentiment == "negative"
        assert score < 0

    def test_neutral_sentiment(self, service):
        text = "Xin chào, tôi muốn hỏi thông tin về sản phẩm"
        sentiment, score = service._analyze_sentiment(text)
        assert sentiment == "neutral"


class TestTopics:
    def test_detects_payment_topic(self, service):
        text = "Tôi muốn thanh toán đơn hàng và trả tiền qua chuyển khoản"
        topics = service._extract_topics(text, [])
        assert "payment" in topics

    def test_detects_complaint_topic(self, service):
        text = "Tôi muốn khiếu nại về đơn hàng bị hỏng và phàn nàn dịch vụ"
        topics = service._extract_topics(text, [])
        assert "complaint" in topics


class TestFullEnrichment:
    def test_full_pipeline(self, service):
        text = (
            "Xin chào, tôi là Nguyễn Văn A, số điện thoại 0912345678. "
            "Tôi muốn khiếu nại về đơn hàng ngày 15/03/2026. "
            "Tổng số tiền là 500.000 đồng nhưng hàng bị hỏng. "
            "Tôi rất thất vọng. Bạn cần kiểm tra lại và gọi lại cho tôi."
        )
        result = service.enrich(text, "vi")
        assert result.summary is not None
        assert len(result.phone_numbers_mentioned) >= 1
        assert len(result.dates_mentioned) >= 1
        assert len(result.amounts_mentioned) >= 1
        assert len(result.action_items) >= 1
        assert result.sentiment == "negative"
        assert "complaint" in result.topics
