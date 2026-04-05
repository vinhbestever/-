# Kiến trúc chi tiết — Call Log Service

## Thiết kế

Service hỗ trợ 2 luồng nhận dữ liệu:

1. **Đồng bộ** (`POST /call-logs`): Khi utterances đã có sẵn → embed + index ngay
2. **Bất đồng bộ** (`POST /ingest`): Gửi audio URL → service tự gọi STT API trong background

## Vấn đề: STT API chậm khi nhiều request

STT API thường xử lý chậm (vài giây đến vài phút/cuộc gọi) và dễ bị quá tải khi nhận nhiều request cùng lúc. Giải pháp:

### asyncio.Queue + Worker Pool + Semaphore

```
POST /ingest (trả 202 ngay)
    │
    ▼
asyncio.Queue (bounded, max 1000)
    │
    ├── Worker 0 ──┐
    ├── Worker 1 ──┤
    └── Worker 2 ──┘
                   │
                   ▼
         asyncio.Semaphore (max 5 concurrent)
                   │
                   ▼
             STT API call
                   │
                   ▼
              embed (5ms)
                   │
                   ▼
            index vào ES
```

**Tại sao cách này đủ, không cần Kafka hay Redis Queue:**

- `asyncio.Queue` là bounded queue trong memory — backpressure tự nhiên khi queue đầy
- Worker pool (`INGEST_WORKER_COUNT=3`) chạy song song, dequeue và xử lý
- `asyncio.Semaphore` (`STT_MAX_CONCURRENCY=5`) giới hạn số request đồng thời tới STT API, bảo vệ STT khỏi quá tải
- Tất cả chạy trong cùng event loop của FastAPI, không cần thêm infra
- Job status tracking in-memory, client poll qua `GET /ingest/{job_id}`

**Khi nào cần nâng cấp:**

- **Multi-instance**: Nếu chạy nhiều API instances, queue in-memory không share được → chuyển sang Redis Queue hoặc Celery
- **Durability**: Nếu cần đảm bảo không mất job khi service restart → thêm persistent queue (Redis, PostgreSQL)

## Data Flow chi tiết

### Luồng bất đồng bộ

```
Client                    Call Log Service                   STT API        Elasticsearch
  │                            │                               │                │
  │── POST /ingest ──────────▶│                               │                │
  │                            │── put vào Queue              │                │
  │◀── 202 {job_id, queued} ──│                               │                │
  │                            │                               │                │
  │                            │── Worker dequeue ────────────▶│                │
  │                            │   (Semaphore acquire)         │                │
  │                            │                               │── transcribe   │
  │                            │                               │   (chậm...)    │
  │── GET /ingest/{id} ──────▶│                               │                │
  │◀── {status: calling_stt} ─│                               │                │
  │                            │◀── utterances ────────────────│                │
  │                            │   (Semaphore release)         │                │
  │                            │── embed(full_text) ──▶ vector │                │
  │                            │── index(doc) ─────────────────────────────────▶│
  │                            │                               │                │
  │── GET /ingest/{id} ──────▶│                               │                │
  │◀── {status: done} ────────│                               │                │
```

### Luồng đồng bộ

```
Client ── POST /call-logs ──▶ embed ──▶ index ──▶ 201 response
```

## Cơ chế bảo vệ STT API

| Cơ chế | Config | Mục đích |
|--------|--------|----------|
| **Semaphore** | `STT_MAX_CONCURRENCY=5` | Giới hạn request đồng thời tới STT |
| **Queue bounded** | `INGEST_QUEUE_MAX_SIZE=1000` | Reject request khi queue đầy (backpressure) |
| **Retry + backoff** | `STT_MAX_RETRIES=3`, exponential 2-30s | Tự retry khi STT timeout/lỗi mạng |
| **Timeout** | `STT_TIMEOUT_SECONDS=300` | Không chờ vô hạn |

## Elasticsearch Mapping

### dense_vector field

```json
{
  "embedding": {
    "type": "dense_vector",
    "dims": 384,
    "index": true,
    "similarity": "cosine"
  }
}
```

- `index: true` bật HNSW graph cho approximate kNN
- `similarity: cosine` phù hợp với normalized embeddings
- 384 dims từ paraphrase-multilingual-MiniLM-L12-v2

## Search Strategy

### Semantic Search (pure kNN)

Tìm cuộc gọi gần nghĩa nhất. Query "khách hàng không hài lòng về sản phẩm" match được "khiếu nại đơn hàng bị lỗi" dù dùng từ khác.

### Hybrid Search (kNN + BM25)

Kết hợp 2 signal:
- **kNN score**: Ngữ nghĩa giống nhau
- **BM25 score**: Từ khóa khớp chính xác

Elasticsearch tự combine scores. Hybrid thường tốt nhất khi query vừa mang nghĩa vừa chứa từ khóa cụ thể.

## Scaling

- **Vertical**: Tăng `STT_MAX_CONCURRENCY` và `INGEST_WORKER_COUNT`
- **Horizontal**: Chạy nhiều API instances (cần chuyển queue sang Redis)
- **Elasticsearch**: Horizontal scaling qua sharding
