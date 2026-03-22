from pydantic_settings import BaseSettings


class GithubConfig(BaseSettings):
    GITHUB_WEBHOOK_SECRET: str = ""
    GITHUB_TOKEN: str = ""
    SLACK_CHANNEL_ID: str = ""
    SLACK_BOT_TOKEN: str = ""

    model_config = {"env_prefix": ""}


github_config = GithubConfig()
