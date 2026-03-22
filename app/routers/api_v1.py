"""Public integration API — /api/v1/"""
from fastapi import APIRouter

from app.routers.api_v1_channels import router as channels_router
from app.routers.api_v1_documents import router as documents_router
from app.routers.api_v1_sessions import router as sessions_router
from app.routers.api_v1_tasks import router as tasks_router
from app.routers.api_v1_todos import router as todos_router

router = APIRouter(prefix="/api/v1")
router.include_router(channels_router)
router.include_router(documents_router)
router.include_router(sessions_router)
router.include_router(tasks_router)
router.include_router(todos_router)
