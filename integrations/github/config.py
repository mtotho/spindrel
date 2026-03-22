from pydantic_settings import BaseSettings


class GithubConfig(BaseSettings):
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_TOKEN: str = ""
    AGENT_SESSION_ID: str = ""

    model_config = {"env_prefix": ""}


github_config = GithubConfig()
