# Kiến trúc chi tiết — Call Log Service

## Tổng quan

Service có một luồng duy nhất: nhận `audio_url` → gọi STT API trong background → embed → lưu Elasticsearch → search.

Không dùng Kafka, Redis, hay Celery. Toàn bộ xử lý bất đồng bộ chạy trong `asyncio` event loop của FastAPI.

## Data Flow

```
Client                    Call Log Service                   STT API        Elasticsearch
  │                            │                               │                │
  │── POST /ingest ──────────▶│                               │                │
  │   {audio_url}              │── put_nowait vào Queue       │                │
  │                            │   (429 nếu queue đầy)        │                │
  │◀── 202 {job_id, queued} ──│                               │                │
  │                            │                               │                │
  │                            │── Worker dequeue              │                │
  │                            │── Semaphore acquire ─────────▶│                │
  │                            │                               │── transcribe   │
  │── GET /ingest/{id} ──────▶│                               │   (chậm...)    │
  │◀── {status: calling_stt} ─│                               │                │
  │                            │◀── utterances ────────────────│                │
  │                            │── Semaphore release           │                │
  │                            │                               │                │
  │                            │── embed (run_in_executor) ──▶ vector           │
  │                            │── index ──────────────────────────────────────▶│
  │                            │                               │                │
  │── GET /ingest/{id} ──────▶│                               │                │
  │◀── {status: done} ────────│                               │                │
  │                            │                               │                │
  │── POST /search/semantic ──▶│                               │                │
  │                            │── embed query ──▶ vector      │                │
  │                            │── kNN search ─────────────────────────────────▶│
  │◀── results ───────────────│◀───────────────────────────────────────────────│
```

## Tại sao asyncio.Queue, không phải Kafka/Redis/Celery

| Yếu tố | asyncio.Queue | Kafka/Redis/Celery |
|---------|---------------|-------------------|
| Infra thêm | Không | Cần broker (Redis/RabbitMQ) |
| RAM cho embedding | 1 bản model (~500MB) | N bản model (N worker processes) |
| Concurrency control | Semaphore trong 1 event loop | Distributed lock phức tạp |
| Phù hợp cho | I/O-bound (chờ STT API) | CPU-bound nặng |
| Job status granularity | 6 trạng thái chi tiết | PENDING/STARTED/SUCCESS/FAILURE |
| Khi nào cần nâng cấp | Multi-instance, cần durability | — |

Nút cổ chai là **STT API call** (I/O-bound, vài giây đến vài phút). `asyncio` + `Semaphore` xử lý I/O concurrency với gần zero overhead, không cần process riêng.

## Ingest Queue — Chi tiết

```
POST /ingest
    │
    ▼
put_nowait()  ───▶  asyncio.Queue (bounded, max 1000)
                         │
                         │  (nếu đầy → QueueFullError → API trả 429)
                         │
                    ┌────┴────┐
                    │ Workers │  (INGEST_WORKER_COUNT, default 3)
                    └────┬────┘
                         │
                         ▼
              asyncio.Semaphore (STT_MAX_CONCURRENCY, default 5)
                         │
                    ┌────┴────┐
                    │ STT API │  tenacity retry (3 lần, backoff 2-30s)
                    └────┬────┘
                         │
                         ▼
              run_in_executor ──▶ embed (thread pool, không block event loop)
                         │
                         ▼
                   Elasticsearch index
                         │
                         ▼
                  job.status = DONE
```

### Cơ chế bảo vệ

| Cơ chế | Vị trí | Mục đích |
|--------|--------|----------|
| `put_nowait` + 429 | `submit()` | API không bao giờ bị treo khi queue đầy |
| `Semaphore(5)` | `_process_job()` | STT API không bị quá tải |
| `run_in_executor` | `_process_job()` | Embed không block event loop |
| TTL cleanup (1h) | `_cleanup_loop()` | Jobs xong bị xóa, không leak memory |
| Graceful shutdown (30s) | `stop()` | Chờ in-flight jobs xong trước khi tắt |
| Retry + backoff | `stt_client.transcribe()` | Tự retry khi STT timeout/lỗi mạng |

### Job Lifecycle

```
QUEUED → CALLING_STT → EMBEDDING → INDEXING → DONE
                                              ↘ FAILED (nếu có lỗi)
```

Client poll `GET /ingest/{job_id}` để biết job đang ở step nào. Jobs `DONE`/`FAILED` tự động bị xóa sau 1 giờ.

## Elasticsearch

### Index Mapping

```
call-logs/
├── call_id           (keyword)
├── direction         (keyword)       — inbound / outbound / internal
├── status            (keyword)       — completed / missed / failed
├── speaker_a         (object)        — {name, phone_number, role}
├── speaker_b         (object)        — {name, phone_number, role}
├── utterances        (nested)        — [{speaker, text, start_time, end_time}]
├── full_text         (text)          — Vietnamese analyzer, BM25 searchable
├── embedding         (dense_vector)  — 384 dims, HNSW index, cosine similarity
├── call_start_time   (date)
├── duration_seconds  (float)
├── language          (keyword)
├── tags              (keyword)
├── metadata          (object)
└── indexed_at        (date)
```

### Vietnamese Analyzer

```json
{
  "vn_analyzer": {
    "type": "custom",
    "tokenizer": "standard",
    "filter": ["lowercase", "asciifolding"]
  }
}
```

`asciifolding` cho phép tìm "khieu nai" match "khiếu nại".

### Search Strategy

**Semantic Search** (`POST /search/semantic`):
- Embed query → kNN tìm cuộc gọi gần nhất về nghĩa
- "Khách phàn nàn sản phẩm hỏng" match "khiếu nại đơn hàng bị lỗi" dù dùng từ khác

**Hybrid Search** (`POST /search/hybrid`):
- Kết hợp kNN (ngữ nghĩa) + BM25 (từ khóa chính xác)
- Elasticsearch tự combine scores
- Tốt nhất khi query vừa mang nghĩa vừa chứa từ khóa cụ thể

Cả hai đều hỗ trợ filters: `direction`, `tags`, `date_from/date_to`.

## Embedding Model

**`paraphrase-multilingual-MiniLM-L12-v2`**:
- 50+ ngôn ngữ bao gồm tiếng Việt
- 384 dims — nhẹ, nhanh (~5ms/sentence trên CPU)
- Normalized → cosine similarity = dot product
- Đổi model khác qua `CALLLOG_EMBEDDING_MODEL`

## Production Features

### Observability

| Feature | Implementation |
|---------|---------------|
| Metrics | Prometheus (`/metrics`): request latency, queue depth, STT duration, embed duration, job counts |
| Tracing | `X-Request-ID` header propagated qua structlog context |
| Logging | JSON (production), Console (debug=true) |
| Health | `/health` — ES connectivity + queue pending count |

### Resilience

| Feature | Implementation |
|---------|---------------|
| STT retry | tenacity: 3 lần, exponential backoff 2-30s |
| Queue backpressure | Bounded queue + 429 khi đầy |
| Event loop safety | Embedding trong thread pool |
| Memory safety | TTL cleanup jobs sau 1h |
| Graceful shutdown | Drain in-flight jobs tối đa 30s |

### Docker

- Multi-stage build (image nhẹ)
- Non-root user (`appuser`)
- Built-in HEALTHCHECK
- uvloop (event loop nhanh hơn ~25%)

## Scaling

| Hướng | Cách |
|-------|------|
| **Vertical** | Tăng `STT_MAX_CONCURRENCY`, `INGEST_WORKER_COUNT` |
| **Horizontal** | Nhiều API instances sau load balancer (mỗi instance có queue riêng, LB phân đều) |
| **Elasticsearch** | Thêm shard / node |
| **Khi cần shared queue** | Chuyển sang arq (async Redis queue) — nhẹ, tương thích asyncio |
