"""SentinelAI Memory and Context Service.

Provides hierarchical memory management, incident-aware context windows,
and context prioritization for AI agents.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from collections import deque

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, Field

from sentinelai.config import settings
from sentinelai.logging import get_logger, setup_logging
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("memory-context")
init_tracing("memory-context")

router = APIRouter(prefix="/api/v1/memory", tags=["Memory"])


# =============================================================================
# Memory Types
# =============================================================================


class MemoryType:
    """Memory type constants."""
    EPISODIC = "episodic"  # Specific incident memories
    SEMANTIC = "semantic"  # General knowledge
    WORKING = "working"    # Current context
    LONG_TERM = "long_term"  # Persistent knowledge


# =============================================================================
# Memory Store (In-Memory Implementation)
# =============================================================================


class MemoryStore:
    """In-memory memory store with TTL and eviction."""

    def __init__(self, max_size: int = 10000):
        self.max_size = max_size
        self._store: dict[str, dict[str, Any]] = {}
        self._access_order = deque(maxlen=max_size)

    def add(self, key: str, value: Any, memory_type: str = "episodic", ttl_seconds: int = 86400) -> None:
        """Add a memory entry."""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        
        self._store[key] = {
            "value": value,
            "type": memory_type,
            "created_at": datetime.now(timezone.utc),
            "expires_at": expires_at,
            "access_count": 0,
        }
        
        # Update access order
        if key not in self._access_order:
            self._access_order.append(key)
        
        # Evict if necessary
        while len(self._store) > self.max_size:
            oldest_key = self._access_order.popleft()
            if oldest_key in self._store:
                del self._store[oldest_key]

    def get(self, key: str) -> Any | None:
        """Get a memory entry."""
        if key not in self._store:
            return None
        
        entry = self._store[key]
        
        # Check expiration
        if entry["expires_at"] < datetime.now(timezone.utc):
            del self._store[key]
            self._access_order.remove(key)
            return None
        
        # Update access
        entry["access_count"] += 1
        self._access_order.remove(key)
        self._access_order.append(key)
        
        return entry["value"]

    def search(self, query: str, memory_type: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories by keyword."""
        results = []
        query_lower = query.lower()
        
        for key, entry in self._store.items():
            # Check expiration
            if entry["expires_at"] < datetime.now(timezone.utc):
                continue
            
            # Filter by type
            if memory_type and entry["type"] != memory_type:
                continue
            
            # Search in value
            value_str = str(entry["value"]).lower()
            if query_lower in value_str:
                results.append({
                    "key": key,
                    "value": entry["value"],
                    "type": entry["type"],
                    "created_at": entry["created_at"].isoformat(),
                    "relevance": value_str.count(query_lower),
                })
        
        # Sort by relevance and recency
        results.sort(key=lambda x: (-x["relevance"], x["created_at"]), reverse=True)
        return results[:limit]

    def delete(self, key: str) -> bool:
        """Delete a memory entry."""
        if key in self._store:
            del self._store[key]
            if key in self._access_order:
                self._access_order.remove(key)
            return True
        return False

    def clear_expired(self) -> int:
        """Clear expired memories."""
        now = datetime.now(timezone.utc)
        expired_keys = [
            key for key, entry in self._store.items()
            if entry["expires_at"] < now
        ]
        
        for key in expired_keys:
            del self._store[key]
            if key in self._access_order:
                self._access_order.remove(key)
        
        return len(expired_keys)


# Global memory store
memory_store = MemoryStore()


# =============================================================================
# Request/Response Models
# =============================================================================


class MemoryCreateRequest(BaseModel):
    """Create memory request."""
    key: str = Field(..., min_length=1)
    value: Any
    memory_type: str = Field("episodic", pattern="^(episodic|semantic|working|long_term)$")
    ttl_seconds: int = Field(86400, ge=60, le=604800)


class MemoryResponse(BaseModel):
    """Memory response."""
    key: str
    value: Any
    memory_type: str
    created_at: datetime
    expires_at: datetime


class ContextRequest(BaseModel):
    """Get context request."""
    incident_id: str
    include_episodic: bool = True
    include_semantic: bool = True
    max_tokens: int = Field(8000, ge=1000, le=32000)


class ContextResponse(BaseModel):
    """Context response."""
    incident_id: str
    context: str
    sources: list[dict[str, Any]]
    token_count: int


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("")
@traced
async def create_memory(
    request: MemoryCreateRequest,
) -> MemoryResponse:
    """Create a new memory entry."""
    memory_store.add(
        key=request.key,
        value=request.value,
        memory_type=request.memory_type,
        ttl_seconds=request.ttl_seconds,
    )
    
    entry = memory_store._store.get(request.key)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create memory",
        )
    
    return MemoryResponse(
        key=request.key,
        value=request.value,
        memory_type=request.memory_type,
        created_at=entry["created_at"],
        expires_at=entry["expires_at"],
    )


@router.get("/{key}")
@traced
async def get_memory(key: str) -> Any:
    """Get a memory entry."""
    value = memory_store.get(key)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )
    return value


@router.delete("/{key}")
@traced
async def delete_memory(key: str) -> dict[str, str]:
    """Delete a memory entry."""
    deleted = memory_store.delete(key)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )
    return {"message": "Memory deleted"}


@router.post("/search")
@traced
async def search_memory(
    query: str = Query(...),
    memory_type: str | None = None,
    limit: int = Query(10, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Search memories."""
    return memory_store.search(query, memory_type, limit)


@router.post("/context")
@traced
async def get_incident_context(
    request: ContextRequest,
) -> ContextResponse:
    """Get context for an incident."""
    context_parts = []
    sources = []
    
    # Get episodic memories (incident-specific)
    if request.include_episodic:
        episodic = memory_store.search(
            f"incident:{request.incident_id}",
            memory_type="episodic",
            limit=5,
        )
        for mem in episodic:
            context_parts.append(f"Incident Memory: {mem['value']}")
            sources.append({"type": "episodic", "key": mem["key"]})
    
    # Get semantic memories (related knowledge)
    if request.include_semantic:
        semantic = memory_store.search(
            request.incident_id,
            memory_type="semantic",
            limit=3,
        )
        for mem in semantic:
            context_parts.append(f"Related Knowledge: {mem['value']}")
            sources.append({"type": "semantic", "key": mem["key"]})
    
    # Combine context
    context = "\n\n".join(context_parts)
    
    # Estimate token count (approximate)
    token_count = len(context) // 4
    
    # Truncate if needed
    max_chars = request.max_tokens * 4
    if len(context) > max_chars:
        context = context[:max_chars] + "..."
        token_count = request.max_tokens
    
    return ContextResponse(
        incident_id=request.incident_id,
        context=context,
        sources=sources,
        token_count=token_count,
    )


@router.post("/cleanup")
@traced
async def cleanup_expired() -> dict[str, int]:
    """Clean up expired memories."""
    count = memory_store.clear_expired()
    return {"cleaned": count}


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Memory Context",
        description="Hierarchical memory and context management",
        version=settings.app_version,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sentinelai.memory_context.main:app",
        host="0.0.0.0",
        port=8011,
        reload=settings.app_debug,
    )
