"""Pipeline configuration via environment variables (INGESTION_ prefix)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionConfig(BaseSettings):
    agent_base_url: str = "http://localhost:8000"
    agent_api_key: str = ""
    classifier_url: str = "http://localhost:8000/v1/chat/completions"
    classifier_model: str = "gpt-4o-mini"
    classifier_timeout: int = 15
    max_body_bytes: int = 50_000
    quarantine_retention_days: int = 90
    layer2_fail_threshold: int = 1  # flags needed to escalate to Layer 3

    model_config = SettingsConfigDict(env_prefix="INGESTION_")
