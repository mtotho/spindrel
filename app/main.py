import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from app.config import VERSION, settings
from app.services.startup_bootstrap import run_startup_bootstrap

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"


def _tlog(label: str, t0: float) -> float:
    """Log elapsed time since t0 and return current time for next section."""
    now = time.monotonic()
    logger.info("[%.1fs] %s", now - t0, label)
    return now


@asynccontextmanager
async def lifespan(application: FastAPI):
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    # Durable JSONL log handler — survives container restarts so the
    # daily health summary can sweep yesterday's evidence even after a redeploy.
    from app.services.log_buffer import install as _install_log_buffer
    from app.services.log_file import install_jsonl_log_handler
    install_jsonl_log_handler()
    _install_log_buffer(capacity=10_000)
    # Validate EMBEDDING_DIMENSIONS — DB columns and halfvec indexes are built for 1536
    if settings.EMBEDDING_DIMENSIONS != 1536:
        raise RuntimeError(
            f"EMBEDDING_DIMENSIONS={settings.EMBEDDING_DIMENSIONS} but DB columns and indexes "
            f"are hardcoded to 1536. Do not change this value — models with different native "
            f"dimensions are zero-padded or Matryoshka-truncated automatically."
        )
    _t_start = time.monotonic()
    bootstrap_result = await run_startup_bootstrap(
        application,
        integration_web_ui_dirs=_INTEGRATION_WEB_UI_DIRS,
    )

    from app.services.startup_runtime import (
        StartupRuntimeHandle,
        shutdown_runtime_services,
        start_boot_background_services,
        start_file_source_watcher,
        start_ready_runtime_services,
    )

    _runtime = StartupRuntimeHandle()
    logger.info("Starting file watcher...")
    start_file_source_watcher(_runtime)

    _t = time.monotonic()
    start_boot_background_services(_runtime, shared_workspace_rows=bootstrap_result.shared_workspace_rows)
    _t = _tlog("Container auto-start, watchers, background warmup launched", _t)

    if settings.STT_PROVIDER:
        logger.info("Warming up STT provider (%s)...", settings.STT_PROVIDER)
        from app.stt import warm_up as stt_warm_up
        stt_warm_up()
        _t = _tlog("STT warmup", _t)
    logger.info("[%.1fs] TOTAL startup (blocking)", time.monotonic() - _t_start)
    logger.info(
        "Agent server ready. (LOG_LEVEL=%s instance=%s network=%s)",
        settings.LOG_LEVEL.upper(),
        settings.SPINDREL_INSTANCE_ID,
        settings.AGENT_NETWORK_NAME or "(none)",
    )
    await start_ready_runtime_services(_runtime)

    try:
        yield
    finally:
        await shutdown_runtime_services(_runtime)


app = FastAPI(
    title="Spindrel",
    description="Self-hosted LLM agent server. Integration API at /api/v1/ — see /docs.",
    version=VERSION,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Chat", "description": "Send messages and stream responses"},
        {"name": "Admin — Bots", "description": "Bot configuration and management"},
        {"name": "Admin — Channels", "description": "Channel CRUD, settings, heartbeats, integrations"},
        {"name": "Admin — Tasks", "description": "Scheduled and deferred task management"},
        {"name": "Admin — Workflows", "description": "Workflow definitions and run management"},
        {"name": "Admin — Carapaces", "description": "Composable expertise bundle management"},
        {"name": "Admin — Providers", "description": "LLM provider configuration"},
        {"name": "Admin — Settings", "description": "Server settings and operations"},
        {"name": "Admin — Users", "description": "User and API key management"},
        {"name": "Admin — Tools", "description": "Tool listing, execution, and policies"},
        {"name": "Admin — Integrations", "description": "Integration activation and configuration"},
        {"name": "Admin — Usage", "description": "Token usage, cost tracking, and budgets"},
        {"name": "Sessions", "description": "Session and message history"},
        {"name": "Discovery", "description": "Endpoint discovery and API documentation"},
    ],
)

# CORS — always allow loopback UI origins for local dev; extend with
# CORS_ORIGINS env var for non-loopback hosts.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_cors_origins: list[str] = [
    "http://localhost:5173",   # Vite dev server
    "http://localhost:8081",
    "http://localhost:19006",  # Expo dev server (legacy)
]
_cors_origins.extend(
    o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"^https?://(localhost|127(?:\.\d{1,3}){3}|\[::1\])(?::\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# Vendored widget runtime — React + ReactDOM + Babel-standalone served
# same-origin so `runtime: react` HTML widgets inside the iframe sandbox
# can <script src="/widget-runtime/..."> them without a CSP carve-out.
# Self-host friendly: no CDN dependency.
from fastapi.staticfiles import StaticFiles  # noqa: E402

_WIDGET_RUNTIME_DIR = Path(__file__).resolve().parent / "static" / "widget-runtime"
if _WIDGET_RUNTIME_DIR.is_dir():
    app.mount(
        "/widget-runtime",
        StaticFiles(directory=str(_WIDGET_RUNTIME_DIR)),
        name="widget-runtime",
    )

# Rate limiting (opt-in, in-memory token bucket)
if settings.RATE_LIMIT_ENABLED:
    from app.services.rate_limiter import RateLimitMiddleware, RateSpec  # noqa: E402
    app.add_middleware(
        RateLimitMiddleware,
        default_spec=RateSpec.parse(settings.RATE_LIMIT_DEFAULT),
        chat_spec=RateSpec.parse(settings.RATE_LIMIT_CHAT),
    )

# Config-mutation middleware: mark config dirty after admin mutations.
# Uses raw ASGI (not BaseHTTPMiddleware) to avoid buffering streaming responses.
from app.services.config_export import is_config_mutation, mark_config_dirty  # noqa: E402


class ConfigExportMiddleware:
    """ASGI middleware that marks config dirty on successful admin mutations."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")

        # Fast path: skip non-mutation requests entirely (zero overhead)
        if not is_config_mutation(method, path):
            await self.app(scope, receive, send)
            return

        status_code = None

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)

        if status_code is not None and status_code < 300:
            mark_config_dirty()


if settings.CONFIG_STATE_FILE:
    app.add_middleware(ConfigExportMiddleware)

# Domain-error → HTTP adapter. Keeps services/agent code out of ``fastapi``.
from app.domain.errors import install_domain_error_handler  # noqa: E402

install_domain_error_handler(app)


# Register routers
from app.routers import auth, chat, sessions, transcribe  # noqa: E402
from app.routers.api_v1 import router as _api_v1_router  # noqa: E402

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(transcribe.router)
app.include_router(_api_v1_router)


_LLMS_TXT = Path(__file__).resolve().parent.parent / "llms.txt"


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
async def llms_txt():
    """Serve the agent-readable project discovery document."""
    if not _LLMS_TXT.is_file():
        raise HTTPException(status_code=404, detail="llms.txt not found")
    return PlainTextResponse(
        _LLMS_TXT.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
    )



@app.get("/health")
async def health():
    from app.config import VERSION
    return {"status": "ok", "version": VERSION}


# ---------------------------------------------------------------------------
# Integration web UI serving (SPA fallback)
# ---------------------------------------------------------------------------
# Registry populated during lifespan by discover_web_uis(); route defined here
# at module level so `app` unambiguously refers to the FastAPI instance.
_INTEGRATION_WEB_UI_DIRS: dict[str, Path] = {}


@app.get("/integrations/{integration_id}/ui/{path:path}")
async def serve_integration_ui(integration_id: str, path: str = ""):
    """Serve integration dashboard files with SPA fallback."""
    dist_dir = _INTEGRATION_WEB_UI_DIRS.get(integration_id)
    if not dist_dir:
        raise HTTPException(status_code=404, detail=f"No web UI for integration '{integration_id}'")

    # Serve exact file if it exists (JS/CSS assets, images, etc.)
    if path:
        file_path = (dist_dir / path).resolve()
        # Security: ensure resolved path doesn't escape dist_dir
        if str(file_path).startswith(str(dist_dir.resolve())) and file_path.is_file():
            from starlette.responses import FileResponse
            return FileResponse(file_path)

    # SPA fallback: serve index.html for any unknown path
    index = dist_dir / "index.html"
    if index.is_file():
        from starlette.responses import FileResponse
        return FileResponse(index, media_type="text/html")

    raise HTTPException(
        status_code=404,
        detail=f"Dashboard not built for '{integration_id}'. "
               f"Run 'npm run build' in the dashboard directory.",
    )


# ---------------------------------------------------------------------------
# Main UI — serve built React SPA from ui-dist/ (baked into Docker image)
# ---------------------------------------------------------------------------
# IMPORTANT: We cannot use app.mount("/", ...) because Starlette Mounts at "/"
# swallow ALL requests including API routes. Instead, we add a lowest-priority
# middleware that serves static files only when no API route matched (404).
_UI_DIST = Path(__file__).resolve().parent.parent / "ui-dist"
if _UI_DIST.is_dir():
    import mimetypes
    from starlette.responses import FileResponse, Response
    from starlette.types import Receive, Scope, Send

    _UI_INDEX = _UI_DIST / "index.html"

    class SPAFallbackMiddleware:
        """ASGI middleware that serves the SPA when the app returns 404.

        Only intercepts GET requests — API POSTs etc. pass through untouched.
        Serves exact file matches from ui-dist/, falls back to index.html
        for client-side routing.
        """
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            path = scope.get("path", "")
            if (
                scope["type"] != "http"
                or scope.get("method", "") != "GET"
                or path.startswith("/api/")
                or path.startswith("/health")
                or path.startswith("/integrations/")
            ):
                await self.app(scope, receive, send)
                return

            # Capture the response status
            response_started = False
            status_code = 0

            async def send_wrapper(message):
                nonlocal response_started, status_code
                if message["type"] == "http.response.start":
                    status_code = message["status"]
                    if status_code != 404:
                        response_started = True
                        await send(message)
                        return
                    # 404 — don't send yet, we'll try the SPA
                    return
                if message["type"] == "http.response.body":
                    if response_started:
                        await send(message)
                        return
                    # This is the 404 body — suppress it, serve SPA instead

            await self.app(scope, receive, send_wrapper)

            if not response_started and status_code == 404:
                # Try serving a static file from ui-dist
                path = scope.get("path", "/").lstrip("/")
                file_path = (_UI_DIST / path).resolve()
                if (
                    path
                    and str(file_path).startswith(str(_UI_DIST.resolve()))
                    and file_path.is_file()
                ):
                    resp = FileResponse(file_path)
                else:
                    resp = FileResponse(_UI_INDEX, media_type="text/html")
                await resp(scope, receive, send)

    app = SPAFallbackMiddleware(app)
