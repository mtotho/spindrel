"""
Example integration router.

This integration is registered at /integrations/example/ automatically on startup.
It demonstrates how to:
  - Expose webhook/callback endpoints
  - Ingest documents via integrations.utils.ingest_document
  - Inject messages into sessions via integrations.utils.inject_message

Remove or replace this integration once you've built a real one.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth
from integrations import utils

router = APIRouter()


@router.get("/ping")
async def ping(_auth: str = Depends(verify_auth)):
    """Health check for this integration."""
    return {"status": "ok", "integration": "example"}


class IngestRequest(BaseModel):
    title: str
    content: str
    session_id: Optional[uuid.UUID] = None
    metadata: dict = {}


@router.post("/ingest", status_code=201)
async def ingest(
    body: IngestRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    """
    Example: ingest a document into the integration document store.
    In a real integration (e.g. gmail) this would be called from a webhook handler.
    """
    doc_id = await utils.ingest_document(
        integration_id="example",
        title=body.title,
        content=body.content,
        session_id=body.session_id,
        metadata=body.metadata,
        db=db,
    )
    return {"doc_id": str(doc_id)}
