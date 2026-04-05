# Kiến trúc chi tiết — Call Log Service

## 1. Tổng quan thiết kế

Service được thiết kế theo mô hình **Event-Driven Architecture** với nguyên tắc:

- **Log-first**: Mọi transcript được index vào Elasticsearch ngay lập tức, đảm bảo không mất dữ liệu
- **Async enrichment**: Xử lý NLP/trích xuất thông tin chạy bất đồng bộ qua Kafka, không block API response
- **Smart retrieval**: Tìm kiếm kết hợp full-text, exact match, fuzzy match, và aggregation

## 2. Lựa chọn Tech Stack

### 2.1 Tại sao Kafka?

**Vấn đề cần giải quyết:**
- Đảm bảo log 100% cuộc gọi (không mất message)
- Tách biệt ingestion (nhanh) với enrichment (chậm hơn)
- Có thể replay lại message nếu enrichment pipeline thay đổi

**Kafka mang lại:**
- **Durability**: Message được persist trên disk, configurable retention
- **Replay**: Consumer có thể seek về offset cũ để xử lý lại
- **Scalability**: Thêm partition + consumer để scale horizontal
- **Decoupling**: API server và enrichment worker hoàn toàn độc lập

**Alternatives đã xem xét:**
- RabbitMQ: Tốt cho task queue nhưng không có replay built-in
- Redis Streams: Nhẹ hơn nhưng kém durability hơn Kafka
- AWS SQS/SNS: Lock-in cloud, không self-hosted

### 2.2 Tại sao Elasticsearch?

- Đã có sẵn hạ tầng (yêu cầu của bạn)
- Full-text search mạnh với nhiều analyzer
- Aggregation engine mạnh cho analytics
- Vietnamese text search với custom analyzer (asciifolding cho dấu)
- Nested queries cho transcript segments
- Horizontal scaling với sharding

### 2.3 Tại sao FastAPI?

- Async/await native — phù hợp với Elasticsearch async client và Kafka
- Auto-generate OpenAPI/Swagger docs
- Pydantic validation — type-safe request/response
- Hiệu năng cao so với Flask/Django cho I/O-bound workload

### 2.4 Tại sao spaCy + Regex?

- spaCy: NER (Named Entity Recognition) nhanh, production-ready
- Regex: Pattern matching chính xác cho SĐT Việt Nam, số tiền VNĐ, ngày tháng VN
- Không cần GPU, chạy được trên CPU
- Dễ mở rộng sang Vietnamese model (PhoBERT) sau này

## 3. Chi tiết Elasticsearch Mapping

### Index Design

Sử dụng **single index** `call-logs` với mapping tối ưu:

```
call-logs/
├── call_id          (keyword)     — ID duy nhất
├── transcript_text  (text)        — Full-text search
│   ├── .vietnamese  (text)        — Vietnamese analyzer
│   └── .keyword     (keyword)     — Exact match
├── transcript_segments (nested)   — Chi tiết từng đoạn
├── caller/callee    (object)      — Thông tin người gọi
├── enriched/        (object)      — Dữ liệu enrichment
│   ├── summary      (text)
│   ├── keywords     (keyword)
│   ├── entities     (nested)
│   ├── sentiment    (keyword)
│   ├── topics       (keyword)
│   └── action_items (text)
├── call_start_time  (date)
├── duration_seconds (float)
└── indexed_at       (date)
```

### Custom Analyzers

- **transcript_analyzer**: `standard` tokenizer + `lowercase` + `asciifolding` + `trim`
- **vietnamese_analyzer**: `standard` tokenizer + `lowercase` + `asciifolding`

`asciifolding` rất quan trọng cho tiếng Việt — cho phép tìm "khieu nai" match "khiếu nại".

## 4. Luồng Enrichment chi tiết

```
Raw transcript text
        │
        ├─▶ Phone number extraction (regex)
        │     VN patterns: 0xxx, +84xxx
        │
        ├─▶ Amount extraction (regex)
        │     Patterns: xxx đồng, xxx VND, $xxx
        │
        ├─▶ Date extraction (regex)
        │     Patterns: dd/mm/yyyy, "ngày X tháng Y"
        │
        ├─▶ Entity extraction (spaCy NER)
        │     PERSON, ORG, GPE, MONEY, DATE
        │
        ├─▶ Keyword extraction (spaCy noun chunks / frequency)
        │
        ├─▶ Action item extraction (keyword matching)
        │     "cần", "phải", "sẽ", "gọi lại"...
        │
        ├─▶ Sentiment analysis (lexicon-based)
        │     positive / negative / neutral
        │
        ├─▶ Topic classification (keyword mapping)
        │     payment, support, complaint, order...
        │
        └─▶ Summary generation (extractive: top 3 sentences)
```

## 5. Search Strategy — "Tìm kiếm thông minh"

### Smart Search (`/smart-search`)

Kết hợp nhiều chiến lược trong một query:

1. **Multi-match** (fuzzy): Tìm trên transcript, summary, keywords, topics, tên người
2. **Phrase match** (boost 5x): Ưu tiên kết quả chứa exact phrase
3. **Term match** (boost 10x): Nếu input là SĐT, match chính xác caller/callee
4. **Highlighting**: Đánh dấu vị trí match trong transcript
5. **Aggregations**: Kèm thống kê by direction, status, sentiment, keywords

### Advanced Search (`/search`)

Structured query với:
- Full-text search (`q`)
- Exact filters (direction, status, caller_phone, language...)
- Range filters (date_from/to, duration_min/max)
- Tag/keyword matching
- Pagination & sorting

## 6. Scaling & Production Considerations

### Elasticsearch
- **ILM Policy**: Hot (7 ngày) → Warm (30 ngày) → Cold (90 ngày) → Delete
- **Shard sizing**: Target 20-40GB/shard
- **Replica**: Minimum 1 replica cho HA

### Kafka
- **Partitions**: 6-12 partitions cho `call-logs-raw` topic
- **Retention**: 7 ngày minimum cho replay capability
- **Consumer group**: Scale enrichment workers horizontal

### API
- **Horizontal scaling**: Stateless, chạy nhiều instances sau load balancer
- **Rate limiting**: Thêm middleware nếu expose public

## 7. Monitoring

- **Health check**: `/health` endpoint check ES connectivity
- **Kafka lag**: Monitor consumer group lag
- **ES cluster health**: Via Kibana hoặc `_cluster/health`
- Có thể thêm Prometheus metrics (đã include `prometheus-client` trong dependencies)

## 8. Roadmap mở rộng

| Ưu tiên | Feature | Mô tả |
|---------|---------|-------|
| P1 | Vietnamese NLP | Thay spaCy bằng PhoBERT/VnCoreNLP |
| P1 | LLM Summarization | Dùng GPT/Claude cho tóm tắt chất lượng |
| P2 | Vector Search | Elasticsearch kNN cho semantic search |
| P2 | Real-time alerts | Cảnh báo khi sentiment < threshold |
| P3 | Audio storage | S3 integration cho file gốc |
| P3 | Dashboard | Kibana dashboards cho analytics |
