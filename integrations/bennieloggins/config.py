"""Bennie Loggins pet health tracker — loaded from environment variables."""

from pydantic_settings import BaseSettings


class BennieLogginConfig(BaseSettings):
    BENNIE_LOGGINS_BASE_URL: str = ""
    BENNIE_LOGGINS_API_KEY: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = BennieLogginConfig()
