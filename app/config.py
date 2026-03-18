from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TIMEZONE: str = "America/New_York"
    # Auth
    API_KEY: str

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://agent:agent@postgres:5432/agentdb"

    # LiteLLM
    LITELLM_BASE_URL: str = "http://litellm:4000/v1"
    LITELLM_API_KEY: str = ""

    # Agent
    AGENT_MAX_ITERATIONS: int = 15
    LOG_LEVEL: str = "INFO"

    # Web tools
    SEARXNG_URL: str = "http://searxng:8080"
    PLAYWRIGHT_WS_URL: str = "ws://playwright:3000"

    # Bennie Loggins (pet health API)
    BENNIE_LOGGINS_BASE_URL: str = "https://bennieloggins.com"
    BENNIE_LOGGINS_API_KEY: str = ""

    # Context compaction
    COMPACTION_MODEL: str = "gemini/gemini-2.5-flash"
    COMPACTION_INTERVAL: int = 30 # Every time there gets to be N turns, the compaction will run.
    COMPACTION_KEEP_TURNS: int = 10 # The last M turns will be kept in context, not included in the compaction. So compaction will only include the last N-M turns.

    # STT / Transcription
    STT_PROVIDER: str = "local"  # "local" (faster-whisper) or future: "groq", "openai"
    WHISPER_MODEL: str = "base.en"
    WHISPER_DEVICE: str = "auto"  # "auto", "cpu", "cuda"
    WHISPER_COMPUTE_TYPE: str = "auto"  # "auto", "int8", "float16", "float32"
    WHISPER_BEAM_SIZE: int = 1
    WHISPER_LANGUAGE: str = "en"

    # RAG (stubbed)
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    RAG_TOP_K: int = 5
    RAG_SIMILARITY_THRESHOLD: float = 0.3

    # Memory
    MEMORY_RETRIEVAL_LIMIT: int = 5
    MEMORY_SIMILARITY_THRESHOLD: float = 0.75
    WIPE_MEMORY_ON_SESSION_DELETE: bool = False

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
