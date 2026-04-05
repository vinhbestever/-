import json
import structlog
from typing import Optional

from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from app.config import settings

logger = structlog.get_logger(__name__)


class KafkaProducerService:
    def __init__(self):
        self._producer: Optional[AIOKafkaProducer] = None

    async def start(self):
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
        )
        await self._producer.start()
        logger.info("Kafka producer started")

    async def stop(self):
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    async def send_raw_call_log(self, call_id: str, data: dict):
        if not self._producer:
            raise RuntimeError("Kafka producer not started")
        await self._producer.send_and_wait(
            topic=settings.kafka_topic_raw,
            key=call_id,
            value=data,
        )
        logger.info("Sent raw call log to Kafka", call_id=call_id, topic=settings.kafka_topic_raw)

    async def send_enriched_call_log(self, call_id: str, data: dict):
        if not self._producer:
            raise RuntimeError("Kafka producer not started")
        await self._producer.send_and_wait(
            topic=settings.kafka_topic_enriched,
            key=call_id,
            value=data,
        )
        logger.info("Sent enriched call log to Kafka", call_id=call_id, topic=settings.kafka_topic_enriched)


class KafkaConsumerService:
    def __init__(self, topic: str, group_id: str):
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._topic = topic
        self._group_id = group_id

    async def start(self):
        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=self._group_id,
            auto_offset_reset=settings.kafka_auto_offset_reset,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        await self._consumer.start()
        logger.info("Kafka consumer started", topic=self._topic, group_id=self._group_id)

    async def stop(self):
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped")

    async def consume(self):
        if not self._consumer:
            raise RuntimeError("Kafka consumer not started")
        async for message in self._consumer:
            yield message


kafka_producer = KafkaProducerService()
