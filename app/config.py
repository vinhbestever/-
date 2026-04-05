from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "call-log-service"
    app_version: str = "1.0.0"
    debug: bool = False

    # Elasticsearch
    elasticsearch_hosts: str = "http://localhost:9200"
    elasticsearch_username: Optional[str] = None
    elasticsearch_password: Optional[str] = None
    elasticsearch_call_log_index: str = "call-logs"
    elasticsearch_call_log_enriched_index: str = "call-logs-enriched"
    elasticsearch_max_retries: int = 3
    elasticsearch_retry_on_timeout: bool = True

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic_raw: str = "call-logs-raw"
    kafka_topic_enriched: str = "call-logs-enriched"
    kafka_consumer_group: str = "call-log-enrichment-group"
    kafka_auto_offset_reset: str = "earliest"

    # NLP / Enrichment
    spacy_model: str = "en_core_web_sm"
    enrichment_enabled: bool = True

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "CALLLOG_", "env_file": ".env"}


settings = Settings()
