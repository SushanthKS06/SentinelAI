"""SentinelAI Vector Retrieval Service.

Provides semantic search capabilities using Qdrant for RAG pipelines,
incident context retrieval, and knowledge base search.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

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
from sentinelai.metrics import metrics
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("vector-retrieval")
init_tracing("vector-retrieval")

router = APIRouter(prefix="/api/v1/vector", tags=["Vector Search"])


# =============================================================================
# Qdrant Client Wrapper
# =============================================================================


class VectorStore:
    """Vector store wrapper for Qdrant."""

    def __init__(self):
        self.client = None
        self.collection_name = settings.qdrant_collection_name
        self._initialized = False

    async def initialize(self):
        """Initialize Qdrant client and collection."""
        if self._initialized:
            return

        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            # Connect to Qdrant
            self.client = QdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
            )

            # Create collection if not exists
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.collection_name not in collection_names:
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=settings.embedding_dimension,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created collection: {self.collection_name}")

            self._initialized = True
            logger.info("Vector store initialized")

        except Exception as e:
            logger.warning(f"Failed to initialize Qdrant: {e}. Using in-memory fallback.")
            self.client = None
            self._initialized = True

    async def add_vectors(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> list[str]:
        """Add vectors to the store."""
        if not self.client:
            return []

        try:
            from qdrant_client.models import PointStruct

            if ids is None:
                ids = [f"vec_{i}" for i in range(len(vectors))]

            points = [
                PointStruct(
                    id=id_,
                    vector=vector,
                    payload=payload,
                )
                for id_, vector, payload in zip(ids, vectors, payloads)
            ]

            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
            )

            metrics.rag_chunks_retrieved.observe(len(vectors))

            return ids

        except Exception as e:
            logger.error(f"Failed to add vectors: {e}")
            return []

    async def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter_conditions: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors."""
        if not self.client:
            return []

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            query_filter = None
            if filter_conditions:
                conditions = []
                for key, value in filter_conditions.items():
                    conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
                query_filter = Filter(must=conditions)

            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=query_filter,
            )

            return [
                {
                    "id": r.id,
                    "score": r.score,
                    "payload": r.payload,
                }
                for r in results
            ]

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    async def delete(self, ids: list[str]) -> bool:
        """Delete vectors by IDs."""
        if not self.client:
            return False

        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=ids,
            )
            return True
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False


# Global vector store
vector_store = VectorStore()


# =============================================================================
# Embedding Service
# =============================================================================


class EmbeddingService:
    """Service for generating embeddings."""

    def __init__(self):
        self.model = None
        self._initialized = False

    async def initialize(self):
        """Initialize the embedding model."""
        if self._initialized:
            return

        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(settings.embedding_model)
            self._initialized = True
            logger.info(f"Embedding model loaded: {settings.embedding_model}")

        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}. Using mock embeddings.")
            self.model = None
            self._initialized = True

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts."""
        if not self.model:
            # Return mock embeddings
            import numpy as np
            return [np.random.rand(settings.embedding_dimension).tolist() for _ in texts]

        try:
            embeddings = self.model.encode(texts, batch_size=settings.embedding_batch_size)
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Embedding generation failed: {e}")
            import numpy as np
            return [np.random.rand(settings.embedding_dimension).tolist() for _ in texts]

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a query."""
        embeddings = await self.embed_texts([query])
        return embeddings[0]


# Global embedding service
embedding_service = EmbeddingService()


# =============================================================================
# Request/Response Models
# =============================================================================


class Document(BaseModel):
    """Document for indexing."""
    text: str = Field(..., min_length=1)
    metadata: dict[str, Any] = {}


class IndexRequest(BaseModel):
    """Index documents request."""
    documents: list[Document] = Field(..., min_length=1, max_length=100)


class SearchRequest(BaseModel):
    """Search request."""
    query: str = Field(..., min_length=1)
    limit: int = Field(10, ge=1, le=100)
    filter: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    """Search response."""
    results: list[dict[str, Any]]
    query: str
    total: int


class HybridSearchRequest(BaseModel):
    """Hybrid search request (BM25 + vector)."""
    query: str = Field(..., min_length=1)
    limit: int = Field(10, ge=1, le=100)
    filters: dict[str, Any] | None = None


# =============================================================================
# API Endpoints
# =============================================================================


@router.on_event("startup")
async def startup():
    """Initialize services on startup."""
    await vector_store.initialize()
    await embedding_service.initialize()


@router.post("/index")
@traced
async def index_documents(
    request: IndexRequest,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Index documents for semantic search."""
    start_time = datetime.now(timezone.utc)

    # Generate embeddings
    texts = [doc.text for doc in request.documents]
    embeddings = await embedding_service.embed_texts(texts)

    # Prepare payloads
    payloads = [
        {
            **doc.metadata,
            "text": doc.text,
            "tenant_id": tenant_id,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        for doc in request.documents
    ]

    # Add to vector store
    ids = await vector_store.add_vectors(embeddings, payloads)

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    metrics.rag_retrieval_duration.labels(stage="index").observe(duration)

    return {
        "indexed": len(ids),
        "ids": ids,
    }


@router.post("/search")
@traced
async def semantic_search(
    request: SearchRequest,
    tenant_id: str = Query(...),
) -> SearchResponse:
    """Semantic search using vector similarity."""
    start_time = datetime.now(timezone.utc)

    # Generate query embedding
    query_vector = await embedding_service.embed_query(request.query)

    # Add tenant filter
    filters = request.filter or {}
    filters["tenant_id"] = tenant_id

    # Search
    results = await vector_store.search(
        query_vector=query_vector,
        limit=request.limit,
        filter_conditions=filters,
    )

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    metrics.rag_retrieval_duration.labels(stage="search").observe(duration)
    metrics.rag_similarity_score.observe(results[0]["score"] if results else 0)

    return SearchResponse(
        results=results,
        query=request.query,
        total=len(results),
    )


@router.post("/hybrid-search")
@traced
async def hybrid_search(
    request: HybridSearchRequest,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Hybrid search combining BM25 and vector search."""
    # This would combine both search methods
    # For now, just use vector search
    search_request = SearchRequest(
        query=request.query,
        limit=request.limit,
        filter=request.filters,
    )
    return await semantic_search(search_request, tenant_id)


@router.get("/collections")
@traced
async def list_collections() -> dict[str, Any]:
    """List available collections."""
    if not vector_store.client:
        return {"collections": []}

    try:
        collections = vector_store.client.get_collections()
        return {
            "collections": [
                {
                    "name": c.name,
                    "vectors_count": c.vectors_count,
                }
                for c in collections.collections
            ]
        }
    except Exception as e:
        logger.error(f"Failed to list collections: {e}")
        return {"collections": [], "error": str(e)}


@router.delete("/documents")
@traced
async def delete_documents(
    ids: list[str] = Query(...),
) -> dict[str, Any]:
    """Delete documents by IDs."""
    deleted = await vector_store.delete(ids)
    return {"deleted": deleted, "count": len(ids)}


# =============================================================================
# RAG Pipeline Endpoints
# =============================================================================


@router.post("/rag")
@traced
async def rag_pipeline(
    query: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Complete RAG pipeline with retrieval and context preparation."""
    start_time = datetime.now(timezone.utc)

    # 1. Generate query embedding
    query_vector = await embedding_service.embed_query(query)

    # 2. Retrieve relevant documents
    results = await vector_store.search(
        query_vector=query_vector,
        limit=limit,
        filter_conditions={"tenant_id": tenant_id},
    )

    # 3. Prepare context
    context = "\n\n".join([
        r["payload"].get("text", "")
        for r in results
    ])

    # 4. Truncate to max tokens
    # Approximate: 1 token ≈ 4 characters
    max_chars = settings.rag_max_context_tokens * 4
    if len(context) > max_chars:
        context = context[:max_chars] + "..."

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    metrics.rag_retrieval_duration.labels(stage="full").observe(duration)

    return {
        "query": query,
        "context": context,
        "sources": [
            {
                "id": r["id"],
                "score": r["score"],
                "text": r["payload"].get("text", "")[:200],
            }
            for r in results
        ],
        "retrieval_time_ms": int(duration * 1000),
    }


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Vector Retrieval",
        description="Semantic search and RAG pipeline",
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
        "sentinelai.vector_retrieval.main:app",
        host="0.0.0.0",
        port=8007,
        reload=settings.app_debug,
    )
