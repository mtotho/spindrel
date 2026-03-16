import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent.bots import load_bots
from app.db.engine import run_migrations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    logger.info("Running database migrations...")
    await run_migrations()
    # Re-init logging — alembic's fileConfig wipes our handlers
    logging.basicConfig(level=logging.INFO, force=True)
    logger.info("Loading bot configurations...")
    load_bots()
    # Import local tools to trigger @register decorators
    import app.tools.local  # noqa: F401

    logger.info("Agent server ready.")
    yield


app = FastAPI(title="Agent Server", lifespan=lifespan)

# Register routers
from app.routers import chat, sessions  # noqa: E402

app.include_router(chat.router)
app.include_router(sessions.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
