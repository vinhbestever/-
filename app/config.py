from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "call-log-service"
    app_version: str = "2.0.0"
    debug: bool = False

    # Elasticsearch
    elasticsearch_hosts: str = "http://localhost:9200"
    elasticsearch_username: Optional[str] = None
    elasticsearch_password: Optional[str] = None
    elasticsearch_call_log_index: str = "call-logs"
    elasticsearch_max_retries: int = 3
    elasticsearch_retry_on_timeout: bool = True

    # Embedding
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_dims: int = 384

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"

    # Logging
    log_level: str = "INFO"

    model_config = {"env_prefix": "CALLLOG_", "env_file": ".env"}


settings = Settings()
