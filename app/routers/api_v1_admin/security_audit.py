"""Security self-assessment endpoint: GET /admin/security-audit."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.security_audit import SecurityAuditResponse, run_security_audit

router = APIRouter()


@router.get("/security-audit", response_model=SecurityAuditResponse)
async def security_audit(db: AsyncSession = Depends(get_db)):
    return await run_security_audit(db)
