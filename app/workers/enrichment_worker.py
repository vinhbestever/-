"""
Kafka consumer worker that reads raw call logs, enriches them via the
enrichment pipeline, and writes the enrichment back to Elasticsearch.

Run standalone:  python -m app.workers.enrichment_worker
"""

import asyncio
import json
import structlog

from app.config import settings
from app.services.kafka_service import KafkaConsumerService, kafka_producer
from app.services.elasticsearch_service import es_service
from app.services.enrichment_service import enrichment_service
from app.models.call_log import EnrichedData

logger = structlog.get_logger(__name__)


async def process_message(message) -> None:
    data = message.value
    call_id = data.get("call_id")
    transcript_text = data.get("transcript_text", "")
    language = data.get("language", "vi")

    if not call_id or not transcript_text:
        logger.warning("Skipping message with missing call_id or transcript_text")
        return

    logger.info("Enriching call log", call_id=call_id)

    try:
        enriched = enrichment_service.enrich(transcript_text, language)
        await es_service.update_enrichment(call_id, enriched)

        await kafka_producer.send_enriched_call_log(
            call_id=call_id,
            data={
                "call_id": call_id,
                "enriched": enriched.model_dump(mode="json"),
            },
        )

        logger.info("Enrichment complete", call_id=call_id, topics=enriched.topics)
    except Exception:
        logger.exception("Failed to enrich call log", call_id=call_id)


async def run_worker():
    logger.info("Starting enrichment worker")

    await es_service.ensure_index()

    consumer = KafkaConsumerService(
        topic=settings.kafka_topic_raw,
        group_id=settings.kafka_consumer_group,
    )

    await kafka_producer.start()
    await consumer.start()

    try:
        async for message in consumer.consume():
            await process_message(message)
    except asyncio.CancelledError:
        logger.info("Worker cancelled, shutting down")
    finally:
        await consumer.stop()
        await kafka_producer.stop()
        await es_service.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
