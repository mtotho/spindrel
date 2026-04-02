import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.embeddings import embed_text as _embed
from app.config import settings
from app.db.models import IntegrationDocument
from app.dependencies import get_db, require_scopes

router = APIRouter(prefix="/documents", tags=["Documents"])


class DocumentIn(BaseModel):
    title: Optional[str] = None
    content: str
    integration_id: Optional[str] = None
    session_id: Optional[uuid.UUID] = None
    metadata: dict = {}


class DocumentOut(BaseModel):
    id: uuid.UUID
    integration_id: Optional[str] = None
    session_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    content: str
    metadata: dict = {}

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, doc: IntegrationDocument) -> "DocumentOut":
        return cls(
            id=doc.id,
            integration_id=doc.integration_id,
            session_id=doc.session_id,
            title=doc.title,
            content=doc.content,
            metadata=doc.metadata_,
        )


@router.post("", response_model=DocumentOut, status_code=201)
async def ingest_document(
    body: DocumentIn,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("documents:write")),
):
    """Ingest a document and embed it for semantic search."""
    embed_text = f"{body.title}\n{body.content}" if body.title else body.content
    embedding = await _embed(embed_text)

    doc = IntegrationDocument(
        id=uuid.uuid4(),
        integration_id=body.integration_id,
        session_id=body.session_id,
        title=body.title,
        content=body.content,
        embedding=embedding,
        metadata_=body.metadata,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return DocumentOut.from_orm(doc)


@router.get("/search", response_model=list[DocumentOut])
async def search_documents(
    q: str,
    integration_id: Optional[str] = None,
    session_id: Optional[uuid.UUID] = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("documents:read")),
):
    """Semantic search over integration documents using cosine similarity."""
    query_embedding = await _embed(q)
    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    stmt = (
        select(IntegrationDocument)
        .where(IntegrationDocument.embedding.isnot(None))
        .order_by(text(f"embedding <=> '{embedding_str}'::vector"))
        .limit(limit)
    )
    if integration_id is not None:
        stmt = stmt.where(IntegrationDocument.integration_id == integration_id)
    if session_id is not None:
        stmt = stmt.where(IntegrationDocument.session_id == session_id)

    result = await db.execute(stmt)
    return [DocumentOut.from_orm(doc) for doc in result.scalars().all()]


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("documents:read")),
):
    """Fetch a document by ID."""
    doc = await db.get(IntegrationDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentOut.from_orm(doc)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("documents:write")),
):
    """Delete a document by ID."""
    doc = await db.get(IntegrationDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.commit()
