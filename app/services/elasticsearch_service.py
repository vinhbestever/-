import structlog
from datetime import datetime
from elasticsearch import AsyncElasticsearch, NotFoundError
from typing import Optional

from app.config import settings
from app.models.call_log import (
    CallLogDocument,
    SearchQuery,
    SearchResult,
    CallLogResponse,
    EnrichedData,
)

logger = structlog.get_logger(__name__)

CALL_LOG_MAPPING = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "vietnamese_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding"],
                },
                "transcript_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "asciifolding", "trim"],
                },
            }
        },
    },
    "mappings": {
        "properties": {
            "call_id": {"type": "keyword"},
            "direction": {"type": "keyword"},
            "status": {"type": "keyword"},
            "caller": {
                "type": "object",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "phone_number": {"type": "keyword"},
                    "role": {"type": "keyword"},
                },
            },
            "callee": {
                "type": "object",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "phone_number": {"type": "keyword"},
                    "role": {"type": "keyword"},
                },
            },
            "participants": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text"},
                    "phone_number": {"type": "keyword"},
                    "role": {"type": "keyword"},
                },
            },
            "transcript_text": {
                "type": "text",
                "analyzer": "transcript_analyzer",
                "fields": {
                    "vietnamese": {
                        "type": "text",
                        "analyzer": "vietnamese_analyzer",
                    },
                    "keyword": {"type": "keyword", "ignore_above": 32766},
                },
                "index_options": "offsets",
            },
            "transcript_segments": {
                "type": "nested",
                "properties": {
                    "speaker": {"type": "keyword"},
                    "text": {"type": "text", "analyzer": "transcript_analyzer"},
                    "start_time": {"type": "float"},
                    "end_time": {"type": "float"},
                    "confidence": {"type": "float"},
                },
            },
            "call_start_time": {"type": "date"},
            "call_end_time": {"type": "date"},
            "duration_seconds": {"type": "float"},
            "language": {"type": "keyword"},
            "source_system": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "metadata": {"type": "object", "enabled": True},
            "enriched": {
                "type": "object",
                "properties": {
                    "summary": {"type": "text", "analyzer": "transcript_analyzer"},
                    "keywords": {"type": "keyword"},
                    "entities": {
                        "type": "nested",
                        "properties": {
                            "text": {"type": "text"},
                            "label": {"type": "keyword"},
                            "start": {"type": "integer"},
                            "end": {"type": "integer"},
                        },
                    },
                    "sentiment": {"type": "keyword"},
                    "sentiment_score": {"type": "float"},
                    "topics": {"type": "keyword"},
                    "action_items": {"type": "text"},
                    "phone_numbers_mentioned": {"type": "keyword"},
                    "dates_mentioned": {"type": "keyword"},
                    "amounts_mentioned": {"type": "keyword"},
                },
            },
            "indexed_at": {"type": "date"},
            "enriched_at": {"type": "date"},
        }
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

    async def ensure_index(self):
        client = await self.get_client()
        index_name = settings.elasticsearch_call_log_index
        if not await client.indices.exists(index=index_name):
            await client.indices.create(index=index_name, body=CALL_LOG_MAPPING)
            logger.info("Created Elasticsearch index", index=index_name)
        else:
            logger.info("Elasticsearch index already exists", index=index_name)

    async def index_call_log(self, doc: CallLogDocument) -> str:
        client = await self.get_client()
        result = await client.index(
            index=settings.elasticsearch_call_log_index,
            id=doc.call_id,
            document=doc.model_dump(mode="json"),
        )
        logger.info("Indexed call log", call_id=doc.call_id, result=result["result"])
        return doc.call_id

    async def update_enrichment(self, call_id: str, enriched: EnrichedData):
        client = await self.get_client()
        await client.update(
            index=settings.elasticsearch_call_log_index,
            id=call_id,
            doc={
                "enriched": enriched.model_dump(mode="json"),
                "enriched_at": datetime.utcnow().isoformat(),
            },
        )
        logger.info("Updated enrichment data", call_id=call_id)

    async def get_call_log(self, call_id: str) -> Optional[CallLogDocument]:
        client = await self.get_client()
        try:
            result = await client.get(
                index=settings.elasticsearch_call_log_index, id=call_id
            )
            return CallLogDocument(**result["_source"])
        except NotFoundError:
            return None

    async def search(self, query: SearchQuery) -> SearchResult:
        client = await self.get_client()
        es_query = self._build_search_query(query)

        result = await client.search(
            index=settings.elasticsearch_call_log_index,
            body=es_query,
            from_=(query.page - 1) * query.size,
            size=query.size,
        )

        hits = result["hits"]
        total = hits["total"]["value"]
        results = [CallLogResponse(**hit["_source"]) for hit in hits["hits"]]
        aggregations = result.get("aggregations")

        return SearchResult(
            total=total,
            page=query.page,
            size=query.size,
            results=results,
            aggregations=aggregations,
        )

    async def smart_search(self, text: str, size: int = 20) -> SearchResult:
        """Intelligent search that combines full-text, semantic, and aggregated results."""
        client = await self.get_client()

        body = {
            "query": {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": text,
                                "fields": [
                                    "transcript_text^3",
                                    "transcript_text.vietnamese^2",
                                    "enriched.summary^2",
                                    "enriched.keywords^1.5",
                                    "enriched.topics",
                                    "enriched.action_items",
                                    "caller.name",
                                    "callee.name",
                                    "tags",
                                ],
                                "type": "best_fields",
                                "fuzziness": "AUTO",
                            }
                        },
                        {
                            "match_phrase": {
                                "transcript_text": {
                                    "query": text,
                                    "boost": 5,
                                }
                            }
                        },
                        {
                            "term": {
                                "caller.phone_number": {
                                    "value": text,
                                    "boost": 10,
                                }
                            }
                        },
                        {
                            "term": {
                                "callee.phone_number": {
                                    "value": text,
                                    "boost": 10,
                                }
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            },
            "highlight": {
                "fields": {
                    "transcript_text": {
                        "fragment_size": 200,
                        "number_of_fragments": 3,
                    },
                    "enriched.summary": {},
                },
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
            },
            "aggs": {
                "by_direction": {"terms": {"field": "direction"}},
                "by_status": {"terms": {"field": "status"}},
                "by_sentiment": {"terms": {"field": "enriched.sentiment"}},
                "by_source": {"terms": {"field": "source_system"}},
                "calls_over_time": {
                    "date_histogram": {
                        "field": "call_start_time",
                        "calendar_interval": "day",
                    }
                },
                "avg_duration": {"avg": {"field": "duration_seconds"}},
                "top_keywords": {"terms": {"field": "enriched.keywords", "size": 20}},
            },
            "sort": [{"_score": "desc"}, {"indexed_at": "desc"}],
        }

        result = await client.search(
            index=settings.elasticsearch_call_log_index,
            body=body,
            size=size,
        )

        hits = result["hits"]
        total = hits["total"]["value"]
        results = []
        for hit in hits["hits"]:
            resp = CallLogResponse(**hit["_source"])
            results.append(resp)

        return SearchResult(
            total=total,
            page=1,
            size=size,
            results=results,
            aggregations=result.get("aggregations"),
        )

    async def get_analytics(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict:
        """Get aggregated analytics for call logs."""
        client = await self.get_client()

        filters = []
        if date_from:
            filters.append({"range": {"call_start_time": {"gte": date_from.isoformat()}}})
        if date_to:
            filters.append({"range": {"call_start_time": {"lte": date_to.isoformat()}}})

        query = {"match_all": {}} if not filters else {"bool": {"filter": filters}}

        body = {
            "size": 0,
            "query": query,
            "aggs": {
                "total_calls": {"value_count": {"field": "call_id"}},
                "by_direction": {"terms": {"field": "direction"}},
                "by_status": {"terms": {"field": "status"}},
                "by_sentiment": {"terms": {"field": "enriched.sentiment"}},
                "avg_duration": {"avg": {"field": "duration_seconds"}},
                "max_duration": {"max": {"field": "duration_seconds"}},
                "min_duration": {"min": {"field": "duration_seconds"}},
                "calls_per_day": {
                    "date_histogram": {
                        "field": "call_start_time",
                        "calendar_interval": "day",
                    }
                },
                "top_callers": {
                    "terms": {"field": "caller.phone_number", "size": 10}
                },
                "top_keywords": {
                    "terms": {"field": "enriched.keywords", "size": 30}
                },
                "top_topics": {
                    "terms": {"field": "enriched.topics", "size": 20}
                },
                "by_source_system": {
                    "terms": {"field": "source_system"}
                },
                "by_language": {
                    "terms": {"field": "language"}
                },
            },
        }

        result = await client.search(
            index=settings.elasticsearch_call_log_index, body=body
        )
        return result.get("aggregations", {})

    def _build_search_query(self, query: SearchQuery) -> dict:
        must = []
        filters = []

        if query.q:
            must.append(
                {
                    "multi_match": {
                        "query": query.q,
                        "fields": [
                            "transcript_text^3",
                            "transcript_text.vietnamese^2",
                            "enriched.summary^2",
                            "enriched.keywords",
                            "enriched.topics",
                            "caller.name",
                            "callee.name",
                        ],
                        "fuzziness": "AUTO",
                    }
                }
            )

        if query.call_id:
            filters.append({"term": {"call_id": query.call_id}})
        if query.direction:
            filters.append({"term": {"direction": query.direction.value}})
        if query.status:
            filters.append({"term": {"status": query.status.value}})
        if query.caller_phone:
            filters.append({"term": {"caller.phone_number": query.caller_phone}})
        if query.callee_phone:
            filters.append({"term": {"callee.phone_number": query.callee_phone}})
        if query.language:
            filters.append({"term": {"language": query.language}})
        if query.source_system:
            filters.append({"term": {"source_system": query.source_system}})
        if query.sentiment:
            filters.append({"term": {"enriched.sentiment": query.sentiment}})

        if query.tags:
            filters.append({"terms": {"tags": query.tags}})
        if query.keywords:
            filters.append({"terms": {"enriched.keywords": query.keywords}})

        range_filters = {}
        if query.date_from:
            range_filters.setdefault("call_start_time", {})["gte"] = query.date_from.isoformat()
        if query.date_to:
            range_filters.setdefault("call_start_time", {})["lte"] = query.date_to.isoformat()
        if query.duration_min is not None:
            range_filters.setdefault("duration_seconds", {})["gte"] = query.duration_min
        if query.duration_max is not None:
            range_filters.setdefault("duration_seconds", {})["lte"] = query.duration_max

        for field, conditions in range_filters.items():
            filters.append({"range": {field: conditions}})

        es_query = {
            "query": {
                "bool": {
                    "must": must if must else [{"match_all": {}}],
                    "filter": filters,
                }
            },
            "sort": [{query.sort_by: {"order": query.sort_order}}],
            "aggs": {
                "by_direction": {"terms": {"field": "direction"}},
                "by_status": {"terms": {"field": "status"}},
                "by_sentiment": {"terms": {"field": "enriched.sentiment"}},
            },
        }

        return es_query


es_service = ElasticsearchService()
