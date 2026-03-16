import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.bots import load_bots
from app.config import settings
from app.db.engine import run_migrations

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
    # Import local tools to trigger @register decorators
    import app.tools.local  # noqa: F401

    logger.info("Agent server ready. (LOG_LEVEL=%s)", settings.LOG_LEVEL.upper())
    yield


app = FastAPI(title="Agent Server", lifespan=lifespan)

# Register routers
from app.routers import chat, sessions  # noqa: E402

app.include_router(chat.router)
app.include_router(sessions.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
