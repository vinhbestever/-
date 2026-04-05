import re
import structlog
from typing import Optional

from app.models.call_log import EnrichedData

logger = structlog.get_logger(__name__)

PHONE_PATTERN = re.compile(
    r"(?:\+?84|0)(?:\s?\.?-?)?\d{2,3}(?:\s?\.?-?)?\d{3}(?:\s?\.?-?)?\d{3,4}"
)
AMOUNT_PATTERN = re.compile(
    r"\d[\d.,]*\s*(?:đồng|VND|vnđ|triệu|tỷ|nghìn|ngàn|USD|\$|đ)",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b(?:ngày|tháng|năm)\s+\d{1,2}(?:\s+tháng\s+\d{1,2})?(?:\s+năm\s+\d{2,4})?\b",
    re.IGNORECASE,
)

ACTION_KEYWORDS = [
    "cần", "phải", "sẽ", "hẹn", "gọi lại", "gửi", "chuyển",
    "liên hệ", "xác nhận", "kiểm tra", "báo lại", "thanh toán",
    "need to", "will", "should", "must", "follow up", "send", "check",
]


class EnrichmentService:
    """Extracts structured information from call transcription text
    using regex-based patterns and optional spaCy NLP."""

    def __init__(self):
        self._nlp = None

    def _get_nlp(self):
        if self._nlp is None:
            try:
                import spacy
                self._nlp = spacy.load("en_core_web_sm")
                logger.info("spaCy model loaded")
            except (ImportError, OSError) as e:
                logger.warning("spaCy not available, using regex-only enrichment", error=str(e))
                self._nlp = False
        return self._nlp if self._nlp is not False else None

    def enrich(self, text: str, language: str = "vi") -> EnrichedData:
        keywords = self._extract_keywords(text)
        entities = self._extract_entities(text)
        phone_numbers = self._extract_phone_numbers(text)
        dates = self._extract_dates(text)
        amounts = self._extract_amounts(text)
        action_items = self._extract_action_items(text)
        summary = self._generate_summary(text)
        sentiment, sentiment_score = self._analyze_sentiment(text)
        topics = self._extract_topics(text, keywords)

        return EnrichedData(
            summary=summary,
            keywords=keywords,
            entities=entities,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            topics=topics,
            action_items=action_items,
            phone_numbers_mentioned=phone_numbers,
            dates_mentioned=dates,
            amounts_mentioned=amounts,
        )

    def _extract_phone_numbers(self, text: str) -> list[str]:
        return list(set(PHONE_PATTERN.findall(text)))

    def _extract_dates(self, text: str) -> list[str]:
        return list(set(DATE_PATTERN.findall(text)))

    def _extract_amounts(self, text: str) -> list[str]:
        return list(set(AMOUNT_PATTERN.findall(text)))

    def _extract_action_items(self, text: str) -> list[str]:
        sentences = re.split(r"[.!?\n]", text)
        action_items = []
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            lower = sentence.lower()
            if any(kw in lower for kw in ACTION_KEYWORDS):
                action_items.append(sentence)
        return action_items[:10]

    def _extract_keywords(self, text: str) -> list[str]:
        nlp = self._get_nlp()
        if nlp:
            doc = nlp(text[:10000])
            keywords = set()
            for chunk in doc.noun_chunks:
                if len(chunk.text) > 2:
                    keywords.add(chunk.text.lower().strip())
            for ent in doc.ents:
                keywords.add(ent.text.lower().strip())
            return list(keywords)[:30]

        words = re.findall(r"\b\w{3,}\b", text.lower())
        stop_words = {
            "the", "and", "for", "that", "this", "with", "from", "are", "was",
            "của", "và", "cho", "với", "các", "những", "được", "không", "này",
            "một", "là", "trong", "đã", "có", "tôi", "bạn", "anh", "chị",
        }
        freq = {}
        for w in words:
            if w not in stop_words:
                freq[w] = freq.get(w, 0) + 1
        sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:30]]

    def _extract_entities(self, text: str) -> list[dict]:
        nlp = self._get_nlp()
        if not nlp:
            entities = []
            for match in PHONE_PATTERN.finditer(text):
                entities.append({
                    "text": match.group(),
                    "label": "PHONE",
                    "start": match.start(),
                    "end": match.end(),
                })
            for match in AMOUNT_PATTERN.finditer(text):
                entities.append({
                    "text": match.group(),
                    "label": "MONEY",
                    "start": match.start(),
                    "end": match.end(),
                })
            return entities[:50]

        doc = nlp(text[:10000])
        entities = []
        for ent in doc.ents:
            entities.append({
                "text": ent.text,
                "label": ent.label_,
                "start": ent.start_char,
                "end": ent.end_char,
            })
        for match in PHONE_PATTERN.finditer(text):
            entities.append({
                "text": match.group(),
                "label": "PHONE",
                "start": match.start(),
                "end": match.end(),
            })
        return entities[:50]

    def _generate_summary(self, text: str) -> Optional[str]:
        sentences = re.split(r"[.!?\n]", text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        if not sentences:
            return text[:500] if text else None
        return ". ".join(sentences[:3]) + "."

    def _analyze_sentiment(self, text: str) -> tuple[str, float]:
        positive_words = {
            "tốt", "hay", "cảm ơn", "hài lòng", "xuất sắc", "tuyệt vời", "ok", "đồng ý",
            "good", "great", "thanks", "excellent", "happy", "satisfied", "perfect",
        }
        negative_words = {
            "tệ", "kém", "phàn nàn", "khiếu nại", "thất vọng", "không hài lòng", "lỗi",
            "bad", "poor", "complaint", "disappointed", "error", "problem", "issue", "angry",
        }

        lower = text.lower()
        pos_count = sum(1 for w in positive_words if w in lower)
        neg_count = sum(1 for w in negative_words if w in lower)

        total = pos_count + neg_count
        if total == 0:
            return "neutral", 0.0

        score = (pos_count - neg_count) / total
        if score > 0.2:
            return "positive", round(score, 2)
        elif score < -0.2:
            return "negative", round(score, 2)
        return "neutral", round(score, 2)

    def _extract_topics(self, text: str, keywords: list[str]) -> list[str]:
        topic_map = {
            "thanh toán": "payment", "payment": "payment", "trả tiền": "payment",
            "hỗ trợ": "support", "support": "support", "giúp đỡ": "support",
            "khiếu nại": "complaint", "complaint": "complaint", "phàn nàn": "complaint",
            "đặt hàng": "order", "order": "order", "mua": "order",
            "giao hàng": "delivery", "delivery": "delivery", "vận chuyển": "delivery",
            "bảo hành": "warranty", "warranty": "warranty",
            "hoàn tiền": "refund", "refund": "refund",
            "tư vấn": "consultation", "consultation": "consultation",
            "lịch hẹn": "appointment", "appointment": "appointment", "hẹn": "appointment",
            "kỹ thuật": "technical", "technical": "technical",
            "tài khoản": "account", "account": "account",
        }

        lower = text.lower()
        topics = set()
        for phrase, topic in topic_map.items():
            if phrase in lower:
                topics.add(topic)
        return list(topics)[:10]


enrichment_service = EnrichmentService()
