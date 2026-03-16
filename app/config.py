from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth
    API_KEY: str

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://agent:agent@postgres:5432/agentdb"

    # LiteLLM
    LITELLM_BASE_URL: str = "http://litellm:4000/v1"
    LITELLM_API_KEY: str = ""
    LITELLM_MCP_URL: str = "http://litellm:4000/mcp"

    # Agent
    AGENT_MAX_ITERATIONS: int = 15

    # RAG (stubbed)
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.75

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
