import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.bots import load_bots
from app.agent.skills import load_skills
from app.config import settings
from app.db.engine import run_migrations
from app.tools.mcp import load_mcp_config

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


@asynccontextmanager
async def lifespan(app: FastAPI):
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    logger.info("Running database migrations...")
    await run_migrations()
    logger.info("Loading bot configurations...")
    load_bots()
    logger.info("Loading MCP server config...")
    load_mcp_config()
    # Import local tools to trigger @register decorators
    import app.tools.local  # noqa: F401

    logger.info("Loading skills...")
    await load_skills()
    if settings.STT_PROVIDER:
        logger.info("Warming up STT provider (%s)...", settings.STT_PROVIDER)
        from app.stt import warm_up as stt_warm_up
        stt_warm_up()
    logger.info("Agent server ready. (LOG_LEVEL=%s)", settings.LOG_LEVEL.upper())
    yield


app = FastAPI(title="Agent Server", lifespan=lifespan)

# Register routers
from app.routers import chat, sessions, transcribe  # noqa: E402

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(transcribe.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
