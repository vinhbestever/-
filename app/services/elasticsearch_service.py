import structlog
from elasticsearch import AsyncElasticsearch, NotFoundError
from typing import Optional

from app.config import settings
from app.models.call_log import (
    CallLogDocument,
    CallLogResponse,
    SemanticSearchRequest,
    SearchResult,
)

logger = structlog.get_logger(__name__)


def build_mapping(dims: int) -> dict:
    return {
        "settings": {
            "number_of_shards": 2,
            "number_of_replicas": 1,
            "analysis": {
                "analyzer": {
                    "vn_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"],
                    },
                },
            },
        },
        "mappings": {
            "properties": {
                "call_id": {"type": "keyword"},
                "direction": {"type": "keyword"},
                "status": {"type": "keyword"},
                "speaker_a": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                        "phone_number": {"type": "keyword"},
                        "role": {"type": "keyword"},
                    },
                },
                "speaker_b": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "keyword"},
                        "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                        "phone_number": {"type": "keyword"},
                        "role": {"type": "keyword"},
                    },
                },
                "utterances": {
                    "type": "nested",
                    "properties": {
                        "speaker": {"type": "keyword"},
                        "text": {"type": "text", "analyzer": "vn_analyzer"},
                        "start_time": {"type": "float"},
                        "end_time": {"type": "float"},
                    },
                },
                "full_text": {
                    "type": "text",
                    "analyzer": "vn_analyzer",
                    "index_options": "offsets",
                },
                "call_start_time": {"type": "date"},
                "call_end_time": {"type": "date"},
                "duration_seconds": {"type": "float"},
                "language": {"type": "keyword"},
                "source_system": {"type": "keyword"},
                "tags": {"type": "keyword"},
                "metadata": {"type": "object", "enabled": True},
                "embedding": {
                    "type": "dense_vector",
                    "dims": dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "indexed_at": {"type": "date"},
            },
        },
    }


class ElasticsearchService:
    def __init__(self):
        self._client: Optional[AsyncElasticsearch] = None

    async def get_client(self) -> AsyncElasticsearch:
        if self._client is None:
            kwargs = {
                "hosts": settings.elasticsearch_hosts.split(","),
                "max_retries": settings.elasticsearch_max_retries,
                "retry_on_timeout": settings.elasticsearch_retry_on_timeout,
            }
            if settings.elasticsearch_username and settings.elasticsearch_password:
                kwargs["basic_auth"] = (
                    settings.elasticsearch_username,
                    settings.elasticsearch_password,
                )
            self._client = AsyncElasticsearch(**kwargs)
        return self._client

    async def close(self):
        if self._client:
            await self._client.close()
            self._client = None

    async def ensure_index(self, dims: int):
        client = await self.get_client()
        index_name = settings.elasticsearch_call_log_index
        if not await client.indices.exists(index=index_name):
            await client.indices.create(index=index_name, body=build_mapping(dims))
            logger.info("Created index", index=index_name, dims=dims)
        else:
            logger.info("Index already exists", index=index_name)

    async def index_call_log(self, doc: CallLogDocument) -> str:
        client = await self.get_client()
        result = await client.index(
            index=settings.elasticsearch_call_log_index,
            id=doc.call_id,
            document=doc.model_dump(mode="json"),
        )
        logger.info("Indexed call log", call_id=doc.call_id, result=result["result"])
        return doc.call_id

    async def get_call_log(self, call_id: str) -> Optional[CallLogDocument]:
        client = await self.get_client()
        try:
            result = await client.get(
                index=settings.elasticsearch_call_log_index, id=call_id
            )
            return CallLogDocument(**result["_source"])
        except NotFoundError:
            return None

    async def semantic_search(
        self,
        query_vector: list[float],
        req: SemanticSearchRequest,
    ) -> SearchResult:
        client = await self.get_client()

        filters = []
        if req.direction:
            filters.append({"term": {"direction": req.direction.value}})
        if req.tags:
            filters.append({"terms": {"tags": req.tags}})
        if req.date_from or req.date_to:
            date_range = {}
            if req.date_from:
                date_range["gte"] = req.date_from.isoformat()
            if req.date_to:
                date_range["lte"] = req.date_to.isoformat()
            filters.append({"range": {"call_start_time": date_range}})

        knn = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": req.size,
            "num_candidates": req.size * 5,
        }
        if filters:
            knn["filter"] = {"bool": {"filter": filters}}

        body: dict = {"knn": knn, "size": req.size}
        if req.min_score is not None:
            body["min_score"] = req.min_score

        result = await client.search(
            index=settings.elasticsearch_call_log_index,
            body=body,
        )

        hits = result["hits"]
        total = hits["total"]["value"]
        results = []
        for hit in hits["hits"]:
            source = hit["_source"]
            source.pop("embedding", None)
            resp = CallLogResponse(**source, score=hit["_score"])
            results.append(resp)

        return SearchResult(total=total, results=results)

    async def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        req: SemanticSearchRequest,
    ) -> SearchResult:
        """kNN + full-text BM25, scores combined by Elasticsearch."""
        client = await self.get_client()

        filters = []
        if req.direction:
            filters.append({"term": {"direction": req.direction.value}})
        if req.tags:
            filters.append({"terms": {"tags": req.tags}})
        if req.date_from or req.date_to:
            date_range = {}
            if req.date_from:
                date_range["gte"] = req.date_from.isoformat()
            if req.date_to:
                date_range["lte"] = req.date_to.isoformat()
            filters.append({"range": {"call_start_time": date_range}})

        knn = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": req.size,
            "num_candidates": req.size * 5,
        }
        if filters:
            knn["filter"] = {"bool": {"filter": filters}}

        text_query: dict = {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": ["full_text"],
                            "fuzziness": "AUTO",
                        }
                    }
                ],
            }
        }
        if filters:
            text_query["bool"]["filter"] = filters

        body: dict = {
            "query": text_query,
            "knn": knn,
            "size": req.size,
        }

        result = await client.search(
            index=settings.elasticsearch_call_log_index,
            body=body,
        )

        hits = result["hits"]
        total = hits["total"]["value"]
        results = []
        for hit in hits["hits"]:
            source = hit["_source"]
            source.pop("embedding", None)
            resp = CallLogResponse(**source, score=hit["_score"])
            results.append(resp)

        return SearchResult(total=total, results=results)

    async def list_logs(
        self,
        page: int = 1,
        size: int = 20,
    ) -> SearchResult:
        client = await self.get_client()
        result = await client.search(
            index=settings.elasticsearch_call_log_index,
            body={
                "query": {"match_all": {}},
                "sort": [{"indexed_at": {"order": "desc"}}],
            },
            from_=(page - 1) * size,
            size=size,
        )

        hits = result["hits"]
        total = hits["total"]["value"]
        results = []
        for hit in hits["hits"]:
            source = hit["_source"]
            source.pop("embedding", None)
            results.append(CallLogResponse(**source))

        return SearchResult(total=total, results=results)


es_service = ElasticsearchService()
