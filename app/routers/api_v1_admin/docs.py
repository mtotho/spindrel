"""Admin API — serve documentation markdown files."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()

_DOCS_ROOT = Path(__file__).resolve().parents[3] / "docs"

# Simple mtime-based cache: {path: (mtime, content)}
_cache: dict[str, tuple[float, str]] = {}


@router.get("/docs")
async def get_docs_page(path: str = Query(..., description="Doc path without .md extension, e.g. 'integrations/index'")):
    """Serve a markdown documentation page from the docs/ directory."""
    # Prevent traversal attacks
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    file_path = (_DOCS_ROOT / path).with_suffix(".md")

    # Ensure resolved path stays within docs/
    try:
        file_path.resolve().relative_to(_DOCS_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Doc not found: {path}")

    # mtime cache
    try:
        mtime = os.path.getmtime(file_path)
        cached = _cache.get(path)
        if cached and cached[0] == mtime:
            content = cached[1]
        else:
            content = file_path.read_text()
            _cache[path] = (mtime, content)
    except OSError:
        raise HTTPException(status_code=500, detail="Failed to read doc file")

    return {"content": content, "path": path}
