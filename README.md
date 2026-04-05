# Call Log Service — Lưu & Semantic Search cuộc gọi

Service nhận transcript cuộc gọi, lưu vào Elasticsearch kèm embedding vector, và hỗ trợ tìm kiếm theo ngữ nghĩa (semantic search).

Hỗ trợ 2 chế độ nhận dữ liệu:
- **Đồng bộ** — utterances đã có sẵn từ STT API → embed + lưu ngay
- **Bất đồng bộ** — gửi audio URL → service tự gọi STT API trong background với kiểm soát concurrency

## Kiến trúc

```
                      ┌──────────────────────────────────────┐
                      │         Call Log Service              │
                      │                                      │
 [Đồng bộ]           │  POST /call-logs                     │
 utterances ─────────▶│    → embed → index                   │
                      │                                      │
 [Bất đồng bộ]       │  POST /ingest                        │
 audio_url ──────────▶│    → Queue ──┐                       │
                      │              │ workers (N)           │
 GET /ingest/{id}     │              ▼                       │
 ◀── job status ──────│    ┌──────────────────┐              │
                      │    │ Semaphore (M)     │              │
                      │    │ ┌──► STT API ──┐ │              │
                      │    │ │  (concurrency│ │              │
                      │    │ │   limited)   │ │              │
                      │    │ └──────────────┘ │              │
                      │    └──────┬───────────┘              │
                      │           ▼                          │
                      │    embed → index                     │
                      └───────────┬──────────────────────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │  Elasticsearch   │
                         │  dense_vector    │
                         │  + full_text     │
                         └────────┬────────┘
                                  │
                                  ▼
                         Semantic / Hybrid Search
```

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/api/v1/call-logs` | Lưu call log (utterances đã có sẵn) |
| `POST` | `/api/v1/ingest` | Gửi audio URL → xử lý bất đồng bộ |
| `GET`  | `/api/v1/ingest/{job_id}` | Kiểm tra trạng thái job |
| `GET`  | `/api/v1/ingest` | Thống kê queue |
| `GET`  | `/api/v1/call-logs` | Liệt kê call logs |
| `GET`  | `/api/v1/call-logs/{call_id}` | Chi tiết call log |
| `POST` | `/api/v1/search/semantic` | Tìm kiếm theo ngữ nghĩa |
| `POST` | `/api/v1/search/hybrid` | Tìm kiếm kết hợp (semantic + full-text) |
| `GET`  | `/health` | Health check |

## Cài đặt & Chạy

### Docker Compose

```bash
docker compose up -d
```

### Local development

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Ví dụ sử dụng

### Đồng bộ — utterances đã có sẵn

```bash
curl -X POST http://localhost:8000/api/v1/call-logs \
  -H "Content-Type: application/json" \
  -d '{
    "utterances": [
      {"speaker": "Agent", "text": "Xin chào anh, em có thể giúp gì ạ?"},
      {"speaker": "Customer", "text": "Anh muốn khiếu nại đơn hàng bị hỏng"},
      {"speaker": "Agent", "text": "Dạ em xin lỗi, em chuyển bộ phận xử lý ngay ạ"}
    ],
    "direction": "inbound",
    "tags": ["complaint"]
  }'
```

### Bất đồng bộ — gửi audio URL

```bash
# Gửi job
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "audio_url": "https://storage.example.com/calls/abc123.wav",
    "direction": "inbound",
    "speaker_a": {"name": "Agent Lan", "role": "agent"},
    "speaker_b": {"name": "Khách hàng", "role": "customer"}
  }'
# → 202 {"job_id": "...", "status": "queued"}

# Kiểm tra trạng thái
curl http://localhost:8000/api/v1/ingest/{job_id}
# → {"status": "calling_stt"} / {"status": "embedding"} / {"status": "done"}
```

### Semantic search

```bash
curl -X POST http://localhost:8000/api/v1/search/semantic \
  -H "Content-Type: application/json" \
  -d '{"query": "khách hàng phàn nàn sản phẩm hỏng"}'
```

## Cấu hình quan trọng

| Env var | Default | Mô tả |
|---------|---------|-------|
| `CALLLOG_STT_API_URL` | `http://localhost:8001/transcribe` | URL của STT API |
| `CALLLOG_STT_MAX_CONCURRENCY` | `5` | Số request đồng thời tối đa tới STT API |
| `CALLLOG_INGEST_WORKER_COUNT` | `3` | Số worker xử lý queue |
| `CALLLOG_INGEST_QUEUE_MAX_SIZE` | `1000` | Kích thước tối đa của queue |
| `CALLLOG_STT_TIMEOUT_SECONDS` | `300` | Timeout cho mỗi STT request |
| `CALLLOG_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Model embedding |

## Chạy tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

## Cấu trúc dự án

```
├── app/
│   ├── api/
│   │   └── routes.py                  # API endpoints
│   ├── models/
│   │   └── call_log.py                # Pydantic models
│   ├── services/
│   │   ├── elasticsearch_service.py   # ES indexing + kNN/hybrid search
│   │   ├── embedding_service.py       # sentence-transformers wrapper
│   │   ├── ingest_queue.py            # Async job queue with workers
│   │   └── stt_client.py             # STT API HTTP client with retry
│   ├── config.py
│   └── main.py
├── tests/
├── scripts/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```
