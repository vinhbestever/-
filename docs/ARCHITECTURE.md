# Kiến trúc chi tiết — Call Log Service v2

## Thiết kế

Service đơn giản hóa thành 3 bước: **Store → Embed → Search**.

Giả định: STT API đã trả về cuộc hội thoại phân chia sẵn giữa 2 người nói (speaker diarization done upstream).

## Data Flow

```
STT API response:
  utterances: [
    {speaker: "Agent",    text: "Xin chào..."},
    {speaker: "Customer", text: "Tôi muốn..."},
    ...
  ]
      │
      ▼
Call Log API (POST /call-logs):
  1. Ghép utterances → full_text
  2. Embed full_text → vector [384 dims]
  3. Index {utterances, full_text, vector} → Elasticsearch
      │
      ▼
Elasticsearch document:
  - utterances[]   (nested, searchable per turn)
  - full_text      (text, BM25 searchable)
  - embedding      (dense_vector, kNN indexed)
      │
      ▼
Search:
  - /search/semantic → kNN cosine trên embedding
  - /search/hybrid   → kNN + BM25 combined score
```

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

### Utterances as nested

```json
{
  "utterances": {
    "type": "nested",
    "properties": {
      "speaker": {"type": "keyword"},
      "text": {"type": "text", "analyzer": "vn_analyzer"}
    }
  }
}
```

Cho phép query chính xác "Agent nói gì" hoặc "Customer nói gì" nếu cần.

## Embedding Model

**`paraphrase-multilingual-MiniLM-L12-v2`** được chọn vì:

- Hỗ trợ tiếng Việt native (trained trên 50+ ngôn ngữ)
- 384 dims — tiết kiệm storage so với 768 dims
- Nhanh: ~5ms/sentence trên CPU
- Normalize sẵn → cosine similarity = dot product

Nếu cần chất lượng cao hơn, đổi sang:
- `dangvantuan/vietnamese-embedding` (768 dims, optimized cho tiếng Việt)
- `intfloat/multilingual-e5-large` (1024 dims, SOTA multilingual)

## Search Strategy

### Semantic Search (pure kNN)

Tìm cuộc gọi **gần nghĩa nhất** với query:

```
Query: "khách hàng không hài lòng về sản phẩm"
  → embed → vector
  → kNN top-k cosine similarity
  → trả về cuộc gọi có nội dung tương tự về nghĩa
```

Phù hợp khi query mang tính mô tả, diễn đạt khác nhưng cùng ý.

### Hybrid Search (kNN + BM25)

Kết hợp 2 signal:
- **kNN score**: Ngữ nghĩa giống nhau
- **BM25 score**: Từ khóa khớp chính xác

Elasticsearch tự combine scores. Hybrid thường cho kết quả tốt nhất khi query vừa có ý nghĩa ngữ nghĩa vừa chứa từ khóa cụ thể.

## Scaling

- **Embedding**: Stateless, có thể chạy nhiều API instances
- **Elasticsearch**: Horizontal scaling qua sharding
- **Model loading**: Lazy load, chỉ load 1 lần khi startup
