# Call Log Service

Service nhận audio cuộc gọi, tự động chuyển thành text qua STT API, tạo embedding vector, lưu vào Elasticsearch, và hỗ trợ tìm kiếm theo ngữ nghĩa (semantic search).

## Kiến trúc

```
POST /ingest {audio_url}
    │
    ▼ 202 Accepted (trả ngay)
┌──────────────────────────────────────────────┐
│              Call Log Service                  │
│                                                │
│   asyncio.Queue (bounded, max 1000)           │
│       │                                        │
│       ├── Worker 0 ──┐                         │
│       ├── Worker 1 ──┼── Semaphore (max 5) ──▶ STT API
│       └── Worker 2 ──┘        │                │
│                               ▼                │
│                         embed (5ms)            │
│                               │                │
│                               ▼                │
│                       Elasticsearch            │
│                    (dense_vector + text)        │
└──────────────────────────────────────────────┘
         │
         ▼
GET /ingest/{job_id}    →  poll trạng thái
POST /search/semantic   →  tìm kiếm theo nghĩa
POST /search/hybrid     →  tìm kiếm kết hợp (nghĩa + từ khóa)
```

## Luồng xử lý

1. Client gửi `POST /ingest` với `audio_url` → nhận lại `job_id` + `202 Accepted` ngay lập tức
2. Worker dequeue, gọi **STT API** chuyển audio → utterances (phân chia 2 người nói)
3. Ghép utterances thành `full_text`, chạy qua **embedding model** → vector 384 chiều
4. Index document (utterances + full_text + vector) vào **Elasticsearch**
5. Client poll `GET /ingest/{job_id}` để biết trạng thái: `queued` → `calling_stt` → `embedding` → `indexing` → `done`

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/api/v1/ingest` | Gửi audio URL → xử lý bất đồng bộ (202) |
| `GET`  | `/api/v1/ingest/{job_id}` | Kiểm tra trạng thái job |
| `GET`  | `/api/v1/ingest` | Thống kê queue (pending, by_status) |
| `GET`  | `/api/v1/call-logs` | Liệt kê call logs (phân trang) |
| `GET`  | `/api/v1/call-logs/{call_id}` | Chi tiết một call log |
| `POST` | `/api/v1/search/semantic` | Tìm kiếm theo ngữ nghĩa (kNN cosine) |
| `POST` | `/api/v1/search/hybrid` | Tìm kiếm kết hợp (kNN + BM25 full-text) |
| `GET`  | `/metrics` | Prometheus metrics |
| `GET`  | `/health` | Health check (ES + queue status) |

## Cài đặt & Chạy

### Docker Compose

```bash
docker compose up -d
```

Bao gồm: Elasticsearch, Kibana, Call Log API.

### Local development

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Nếu đã có Elasticsearch sẵn

```bash
export CALLLOG_ELASTICSEARCH_HOSTS=http://your-es-host:9200
export CALLLOG_STT_API_URL=http://your-stt-api:8001/transcribe
uvicorn app.main:app --port 8000
```

## Ví dụ sử dụng

### Gửi cuộc gọi để xử lý

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "audio_url": "https://storage.example.com/calls/abc123.wav",
    "direction": "inbound",
    "speaker_a": {"name": "Agent Lan", "role": "agent"},
    "speaker_b": {"name": "Khách hàng", "role": "customer"},
    "tags": ["support"]
  }'
# → 202 {"job_id": "...", "status": "queued", "message": "Queued for processing (position ~1)"}
```

### Kiểm tra trạng thái

```bash
curl http://localhost:8000/api/v1/ingest/{job_id}
# → {"job_id": "...", "status": "done", "completed_at": "..."}
```

### Tìm kiếm theo ngữ nghĩa

```bash
curl -X POST http://localhost:8000/api/v1/search/semantic \
  -H "Content-Type: application/json" \
  -d '{"query": "khách hàng phàn nàn sản phẩm hỏng"}'
```

### Tìm kiếm kết hợp (semantic + full-text)

```bash
curl -X POST http://localhost:8000/api/v1/search/hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "query": "thanh toán hóa đơn",
    "direction": "inbound",
    "size": 10
  }'
```

### Xem thống kê queue

```bash
curl http://localhost:8000/api/v1/ingest
# → {"queue_pending": 3, "total_jobs": 150, "by_status": {"done": 145, "calling_stt": 2, ...}}
```

## Cấu hình

| Env var | Default | Mô tả |
|---------|---------|-------|
| `CALLLOG_ELASTICSEARCH_HOSTS` | `http://localhost:9200` | Elasticsearch cluster |
| `CALLLOG_STT_API_URL` | `http://localhost:8001/transcribe` | URL của STT API |
| `CALLLOG_STT_MAX_CONCURRENCY` | `5` | Số request đồng thời tối đa tới STT API |
| `CALLLOG_STT_TIMEOUT_SECONDS` | `300` | Timeout cho mỗi STT request |
| `CALLLOG_STT_MAX_RETRIES` | `3` | Số lần retry khi STT timeout |
| `CALLLOG_INGEST_WORKER_COUNT` | `3` | Số worker xử lý queue |
| `CALLLOG_INGEST_QUEUE_MAX_SIZE` | `1000` | Kích thước tối đa queue (trả 429 khi đầy) |
| `CALLLOG_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Model embedding |
| `CALLLOG_EMBEDDING_DIMS` | `384` | Số chiều vector |
| `CALLLOG_CORS_ORIGINS` | `*` | CORS allowed origins |
| `CALLLOG_DEBUG` | `false` | `true` = console log, `false` = JSON log |

## STT API Contract

Service gọi STT API với request/response format sau:

**Request:**
```json
POST {CALLLOG_STT_API_URL}
{"audio_url": "https://...", "language": "vi"}
```

**Expected Response:**
```json
{
  "utterances": [
    {"speaker": "A", "text": "Xin chào", "start_time": 0.0, "end_time": 1.5},
    {"speaker": "B", "text": "Chào bạn", "start_time": 1.6, "end_time": 3.0}
  ]
}
```

## Tech Stack

| Component | Technology | Vai trò |
|-----------|-----------|---------|
| API Framework | FastAPI | Async HTTP server |
| Search & Storage | Elasticsearch | dense_vector kNN + BM25 full-text |
| Embedding | sentence-transformers | Multilingual Vietnamese, 384 dims |
| STT Client | httpx + tenacity | Async HTTP với retry + backoff |
| Queue | asyncio.Queue + Semaphore | Concurrency control, không cần infra thêm |
| Metrics | prometheus-client | Request latency, queue depth, STT/embed duration |
| Logging | structlog | JSON (production) / Console (debug) |

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
│   │   ├── ingest_queue.py            # Async job queue + worker pool
│   │   └── stt_client.py             # STT API HTTP client + retry
│   ├── middleware.py                  # Prometheus metrics + request tracing
│   ├── config.py                      # Settings via env vars
│   └── main.py                        # FastAPI app entry point
├── tests/
│   ├── test_embedding.py
│   ├── test_ingest_queue.py
│   ├── test_models.py
│   └── test_stt_client.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── docs/
    └── ARCHITECTURE.md
```
