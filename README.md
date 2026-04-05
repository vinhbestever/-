# Call Log Service — Lưu & Semantic Search cuộc gọi

Service nhận transcript cuộc gọi (đã phân chia speaker từ STT API), lưu vào Elasticsearch kèm embedding vector, và hỗ trợ tìm kiếm theo ngữ nghĩa (semantic search).

## Kiến trúc

```
┌───────────────────┐
│  Speech-to-Text   │  (API đã có sẵn, trả về utterances phân chia 2 người)
│       API         │
└─────────┬─────────┘
          │ utterances[]
          ▼
┌───────────────────┐      ┌───────────────────────┐
│  Call Log API     │─────▶│  Embedding Model      │
│  (FastAPI)        │      │  (sentence-transformers│
└─────────┬─────────┘      │   multilingual)       │
          │                └───────────────────────┘
          │ doc + vector
          ▼
┌───────────────────┐
│  Elasticsearch    │
│  (dense_vector    │
│   + full_text)    │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Semantic Search  │  kNN cosine similarity
│  Hybrid Search    │  kNN + BM25 full-text
└───────────────────┘
```

## Luồng dữ liệu

1. **STT API** trả về danh sách `utterances` — mỗi utterance gồm `speaker` + `text`, đã phân chia sẵn giữa 2 người nói
2. **Call Log API** nhận utterances, ghép thành `full_text`, chạy qua embedding model → vector 384 chiều
3. **Elasticsearch** lưu document gồm: utterances gốc, full_text, và embedding vector (`dense_vector` + HNSW index)
4. **Search** — 2 chế độ:
   - **Semantic search**: Embed query → kNN tìm cuộc gọi gần nhất về ngữ nghĩa
   - **Hybrid search**: Kết hợp kNN + BM25 full-text để tăng độ chính xác

## API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `POST` | `/api/v1/call-logs` | Lưu call log mới |
| `GET`  | `/api/v1/call-logs` | Liệt kê call logs |
| `GET`  | `/api/v1/call-logs/{call_id}` | Lấy chi tiết |
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

### Nếu đã có Elasticsearch sẵn

```bash
export CALLLOG_ELASTICSEARCH_HOSTS=http://your-es-host:9200
uvicorn app.main:app --reload
```

## Ví dụ sử dụng

### Lưu call log

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
    "speaker_a": {"name": "Agent Lan", "role": "agent"},
    "speaker_b": {"name": "Khách hàng", "role": "customer"},
    "tags": ["complaint"]
  }'
```

### Semantic search

```bash
curl -X POST http://localhost:8000/api/v1/search/semantic \
  -H "Content-Type: application/json" \
  -d '{"query": "khách hàng phàn nàn sản phẩm hỏng"}'
```

### Hybrid search (semantic + full-text)

```bash
curl -X POST http://localhost:8000/api/v1/search/hybrid \
  -H "Content-Type: application/json" \
  -d '{
    "query": "thanh toán hóa đơn",
    "direction": "inbound",
    "size": 10
  }'
```

## Embedding Model

Mặc định dùng `paraphrase-multilingual-MiniLM-L12-v2`:
- Hỗ trợ 50+ ngôn ngữ bao gồm **tiếng Việt**
- Vector 384 chiều — nhẹ, nhanh
- Cosine similarity cho semantic matching

Có thể đổi sang model khác qua biến môi trường `CALLLOG_EMBEDDING_MODEL`.

## Chạy tests

```bash
pip install pytest
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
│   │   └── embedding_service.py       # sentence-transformers wrapper
│   ├── config.py
│   └── main.py
├── tests/
├── scripts/
│   └── create_sample_data.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```
