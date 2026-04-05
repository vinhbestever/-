# Call Log Service — Data Flow cho Log cuộc gọi

Service ghi log và trích xuất thông tin thông minh từ text cuộc gọi (speech-to-text), xây dựng trên **FastAPI + Kafka + Elasticsearch**.

## Kiến trúc tổng quan

```
┌──────────────────┐
│  Speech-to-Text  │  (API đã có sẵn)
│       API        │
└────────┬─────────┘
         │ transcript text
         ▼
┌──────────────────┐     ┌─────────────────────┐
│   Call Log API   │────▶│       Kafka          │
│    (FastAPI)     │     │  topic: call-logs-raw│
└────────┬─────────┘     └──────────┬───────────┘
         │                          │
         │ index ngay               │ async consume
         ▼                          ▼
┌──────────────────┐     ┌─────────────────────┐
│  Elasticsearch   │◀────│  Enrichment Worker  │
│   (call-logs)    │     │  (NLP / Regex)      │
└────────┬─────────┘     └──────────┬───────────┘
         │                          │
         │                          ▼
         │               ┌─────────────────────┐
         │               │       Kafka          │
         │               │topic: call-logs-     │
         │               │       enriched       │
         │               └─────────────────────┘
         ▼
┌──────────────────┐
│  Search / Query  │
│  Smart Search    │
│  Analytics API   │
└──────────────────┘
```

## Luồng dữ liệu (Data Flow)

### 1. Ingestion (Thu thập)
- API nhận transcript text từ hệ thống speech-to-text
- Dữ liệu được **index ngay lập tức** vào Elasticsearch (đảm bảo log 100%)
- Đồng thời publish message lên Kafka topic `call-logs-raw`

### 2. Enrichment (Làm giàu dữ liệu)
Worker tiêu thụ từ Kafka và tự động trích xuất:
- **Tóm tắt** nội dung cuộc gọi
- **Keywords** quan trọng
- **Entities**: tên người, tổ chức, địa điểm
- **Số điện thoại** được nhắc đến trong cuộc gọi
- **Ngày tháng** được đề cập
- **Số tiền** được đề cập
- **Sentiment**: tích cực / tiêu cực / trung lập
- **Topics**: thanh toán, hỗ trợ, khiếu nại, đặt hàng...
- **Action items**: các việc cần làm sau cuộc gọi

### 3. Search & Query (Tìm kiếm thông minh)
- **Full-text search** với fuzzy matching cho tiếng Việt
- **Smart search**: tự động match transcript, số điện thoại, keywords, topics
- **Phrase search** với boost cao cho exact match
- **Filters**: theo hướng gọi, trạng thái, thời gian, sentiment...
- **Aggregations**: thống kê tổng hợp theo nhiều chiều

## Tech Stack

| Component | Technology | Lý do chọn |
|-----------|-----------|-------------|
| **API** | FastAPI (Python) | Async native, tự generate OpenAPI docs, hiệu năng cao |
| **Message Queue** | Apache Kafka | Đảm bảo không mất log, replay được, scale horizontal |
| **Storage & Search** | Elasticsearch | Full-text search mạnh, aggregation, đã có sẵn hạ tầng |
| **NLP** | spaCy + Regex | NER, keyword extraction; regex cho SĐT/tiền/ngày VN |
| **Visualization** | Kibana | Dashboard có sẵn với Elasticsearch |

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/api/v1/call-logs` | Tạo mới call log |
| `GET` | `/api/v1/call-logs/{call_id}` | Lấy call log theo ID |
| `POST` | `/api/v1/call-logs/search` | Tìm kiếm nâng cao với filters |
| `GET` | `/api/v1/call-logs/smart-search/?q=...` | Tìm kiếm thông minh |
| `GET` | `/api/v1/analytics` | Thống kê tổng hợp |
| `POST` | `/api/v1/call-logs/{call_id}/re-enrich` | Chạy lại enrichment |
| `GET` | `/health` | Health check |

## Cài đặt & Chạy

### Docker Compose (khuyên dùng)

```bash
docker compose up -d
```

Bao gồm: Elasticsearch, Kibana, Kafka, API, và Enrichment Worker.

### Chạy local (development)

```bash
# Cài dependencies
pip install -r requirements.txt

# (Tuỳ chọn) Cài spaCy model cho NER
python -m spacy download en_core_web_sm

# Chạy API
uvicorn app.main:app --reload --port 8000

# Chạy enrichment worker (terminal khác)
python -m app.workers.enrichment_worker
```

### Nếu đã có Elasticsearch sẵn

Chỉ cần cấu hình biến môi trường:

```bash
export CALLLOG_ELASTICSEARCH_HOSTS=http://your-es-host:9200
export CALLLOG_ELASTICSEARCH_USERNAME=your_user     # nếu cần
export CALLLOG_ELASTICSEARCH_PASSWORD=your_password  # nếu cần
```

## Ví dụ sử dụng

### Tạo call log

```bash
curl -X POST http://localhost:8000/api/v1/call-logs \
  -H "Content-Type: application/json" \
  -d '{
    "transcript_text": "Xin chào, tôi là Nguyễn Văn A, SĐT 0912345678. Tôi muốn khiếu nại về đơn hàng ngày 15/03/2026. Tổng tiền 500.000 đồng nhưng hàng bị hỏng. Bạn cần kiểm tra và gọi lại cho tôi.",
    "direction": "inbound",
    "status": "completed",
    "caller": {
      "name": "Nguyễn Văn A",
      "phone_number": "0912345678",
      "role": "customer"
    },
    "callee": {
      "name": "Hotline CSKH",
      "phone_number": "19001234",
      "role": "agent"
    },
    "language": "vi",
    "tags": ["complaint", "vip"],
    "duration_seconds": 180
  }'
```

### Tìm kiếm thông minh

```bash
curl "http://localhost:8000/api/v1/call-logs/smart-search/?q=khiếu nại đơn hàng"
```

### Tìm kiếm nâng cao

```bash
curl -X POST http://localhost:8000/api/v1/call-logs/search \
  -H "Content-Type: application/json" \
  -d '{
    "q": "khiếu nại",
    "direction": "inbound",
    "sentiment": "negative",
    "date_from": "2026-01-01T00:00:00",
    "tags": ["complaint"],
    "page": 1,
    "size": 20
  }'
```

## Chạy tests

```bash
pip install pytest
pytest tests/ -v
```

## Cấu trúc dự án

```
├── app/
│   ├── api/
│   │   └── routes.py            # API endpoints
│   ├── models/
│   │   └── call_log.py          # Pydantic models
│   ├── services/
│   │   ├── elasticsearch_service.py  # ES indexing & search
│   │   ├── kafka_service.py          # Kafka producer/consumer
│   │   └── enrichment_service.py     # NLP enrichment pipeline
│   ├── workers/
│   │   └── enrichment_worker.py      # Async Kafka consumer worker
│   ├── utils/
│   ├── config.py                # Settings via env vars
│   └── main.py                  # FastAPI app entry point
├── tests/
├── docs/
│   └── ARCHITECTURE.md          # Chi tiết kiến trúc
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Mở rộng trong tương lai

- **Vector search**: Dùng Elasticsearch kNN để tìm cuộc gọi tương tự về ngữ nghĩa
- **LLM summarization**: Tích hợp OpenAI/local LLM để tóm tắt chất lượng hơn
- **Vietnamese NLP model**: Thay spaCy bằng PhoBERT/VnCoreNLP cho NER tiếng Việt
- **Real-time streaming**: WebSocket push khi có cuộc gọi mới
- **Alerting**: Tự động cảnh báo khi phát hiện sentiment tiêu cực
- **ILM (Index Lifecycle Management)**: Hot/warm/cold cho Elasticsearch
