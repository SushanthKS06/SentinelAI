"""SentinelAI Trace Correlation Service.

Handles distributed trace ingestion, storage, correlation,
and visualization for distributed systems debugging.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
from sentinelai.database import db_manager
from sentinelai.logging import get_logger, setup_logging
from sentinelai.metrics import metrics
from sentinelai.models import (
    Span,
    Trace,
    generate_uuid,
)
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("trace-correlation")
init_tracing("trace-correlation")

router = APIRouter(prefix="/api/v1/traces", tags=["Traces"])


# =============================================================================
# Request/Response Models
# =============================================================================


class TraceIngestRequest(BaseModel):
    """Trace ingestion request."""
    traces: list[dict[str, Any]] = Field(..., min_length=1, max_length=100)
    tenant_id: str


class SpanIngestRequest(BaseModel):
    """Span ingestion request."""
    spans: list[dict[str, Any]] = Field(..., min_length=1, max_length=1000)
    tenant_id: str


class TraceResponse(BaseModel):
    """Trace response."""
    trace_id: str
    start_time: datetime
    end_time: datetime | None
    duration_ms: float | None
    service_name: str
    operation_name: str
    status_code: int | None
    tags: dict[str, Any]
    span_count: int = 0

    class Config:
        from_attributes = True


class SpanResponse(BaseModel):
    """Span response."""
    span_id: str
    parent_span_id: str | None
    operation_name: str
    service_name: str
    start_time: datetime
    end_time: datetime | None
    duration_ms: float | None
    status_code: int | None
    logs: list[dict[str, Any]]
    attributes: dict[str, Any]
    trace_id: str

    class Config:
        from_attributes = True


class TraceDetailResponse(BaseModel):
    """Detailed trace response with spans."""
    trace_id: str
    start_time: datetime
    end_time: datetime | None
    duration_ms: float | None
    service_name: str
    spans: list[SpanResponse]
    services: list[str]
    total_spans: int


# =============================================================================
# Trace Ingestion
# =============================================================================


@router.post("/ingest")
@traced
async def ingest_traces(
    request: TraceIngestRequest,
) -> dict[str, Any]:
    """Ingest trace data."""
    ingested = 0

    async with db_manager.session() as session:
        for trace_data in request.traces:
            try:
                trace = Trace(
                    trace_id=trace_data.get("trace_id"),
                    start_time=trace_data.get("start_time", datetime.now(timezone.utc)),
                    end_time=trace_data.get("end_time"),
                    duration_ms=trace_data.get("duration_ms"),
                    service_name=trace_data.get("service_name", "unknown"),
                    operation_name=trace_data.get("operation_name", "unknown"),
                    status_code=trace_data.get("status_code"),
                    status_message=trace_data.get("status_message"),
                    tags=trace_data.get("tags", {}),
                    metadata=trace_data.get("metadata", {}),
                    tenant_id=request.tenant_id,
                )
                session.add(trace)
                ingested += 1

            except Exception as e:
                logger.error(f"Failed to parse trace: {e}")

        await session.commit()

    metrics.queue_messages_processed.labels(
        queue="trace_ingest",
        topic="traces",
        status="success",
    ).inc(ingested)

    return {
        "ingested": ingested,
    }


@router.post("/spans")
@traced
async def ingest_spans(
    request: SpanIngestRequest,
) -> dict[str, Any]:
    """Ingest span data."""
    ingested = 0

    async with db_manager.session() as session:
        for span_data in request.spans:
            try:
                span = Span(
                    span_id=span_data.get("span_id"),
                    parent_span_id=span_data.get("parent_span_id"),
                    operation_name=span_data.get("operation_name", "unknown"),
                    service_name=span_data.get("service_name", "unknown"),
                    start_time=span_data.get("start_time", datetime.now(timezone.utc)),
                    end_time=span_data.get("end_time"),
                    duration_ms=span_data.get("duration_ms"),
                    status_code=span_data.get("status_code"),
                    status_message=span_data.get("status_message"),
                    logs=span_data.get("logs", []),
                    attributes=span_data.get("attributes", {}),
                    trace_id=span_data.get("trace_id"),
                )
                session.add(span)
                ingested += 1

            except Exception as e:
                logger.error(f"Failed to parse span: {e}")

        await session.commit()

    metrics.queue_messages_processed.labels(
        queue="span_ingest",
        topic="spans",
        status="success",
    ).inc(ingested)

    return {
        "ingested": ingested,
    }


# =============================================================================
# Trace Query
# =============================================================================


@router.get("")
@traced
async def search_traces(
    service: str | None = None,
    operation: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    status_code: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Search traces with filtering."""
    # Default time range: last 1 hour
    if not from_date:
        from_date = datetime.now(timezone.utc) - timedelta(hours=1)
    if not to_date:
        to_date = datetime.now(timezone.utc)

    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select

        # Build query
        query = select(Trace).where(
            and_(
                Trace.tenant_id == tenant_id,
                Trace.start_time >= from_date,
                Trace.start_time <= to_date,
            )
        )

        if service:
            query = query.where(Trace.service_name == service)

        if operation:
            query = query.where(Trace.operation_name == operation)

        if status_code:
            query = query.where(Trace.status_code == status_code)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)

        # Apply pagination
        query = query.order_by(Trace.start_time.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await session.execute(query)
        traces = list(result.scalars().all())

        # Get span counts for each trace
        trace_ids = [t.trace_id for t in traces]
        span_counts = {}
        if trace_ids:
            count_query = select(
                Span.trace_id,
                func.count(Span.span_id).label("count")
            ).where(Span.trace_id.in_(trace_ids)).group_by(Span.trace_id)
            res = await session.execute(count_query)
            for row in res:
                span_counts[row.trace_id] = row.count

        return {
            "traces": [
                {
                    "trace_id": t.trace_id,
                    "start_time": t.start_time,
                    "end_time": t.end_time,
                    "duration_ms": t.duration_ms,
                    "service_name": t.service_name,
                    "operation_name": t.operation_name,
                    "status_code": t.status_code,
                    "span_count": span_counts.get(t.trace_id, 0),
                }
                for t in traces
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/{trace_id}")
@traced
async def get_trace(
    trace_id: str,
    tenant_id: str = Query(...),
) -> TraceDetailResponse:
    """Get trace by ID with all spans."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        # Get trace
        result = await session.execute(
            select(Trace).where(
                and_(
                    Trace.trace_id == trace_id,
                    Trace.tenant_id == tenant_id,
                )
            )
        )
        trace = result.scalar_one_or_none()

        if not trace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trace not found",
            )

        # Get spans
        result = await session.execute(
            select(Span).where(Span.trace_id == trace_id)
        )
        spans = list(result.scalars().all())

        # Get unique services
        services = list(set([s.service_name for s in spans]))

        return TraceDetailResponse(
            trace_id=trace.trace_id,
            start_time=trace.start_time,
            end_time=trace.end_time,
            duration_ms=trace.duration_ms,
            service_name=trace.service_name,
            spans=[SpanResponse(
                span_id=s.span_id,
                parent_span_id=s.parent_span_id,
                operation_name=s.operation_name,
                service_name=s.service_name,
                start_time=s.start_time,
                end_time=s.end_time,
                duration_ms=s.duration_ms,
                status_code=s.status_code,
                logs=s.logs,
                attributes=s.attributes,
                trace_id=s.trace_id,
            ) for s in spans],
            services=services,
            total_spans=len(spans),
        )


@router.get("/{trace_id}/spans")
@traced
async def get_trace_spans(
    trace_id: str,
    tenant_id: str = Query(...),
) -> list[SpanResponse]:
    """Get all spans for a trace."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(Span).where(
                and_(
                    Span.trace_id == trace_id,
                )
            ).order_by(Span.start_time.asc())
        )
        spans = list(result.scalars().all())

        return [
            SpanResponse(
                span_id=s.span_id,
                parent_span_id=s.parent_span_id,
                operation_name=s.operation_name,
                service_name=s.service_name,
                start_time=s.start_time,
                end_time=s.end_time,
                duration_ms=s.duration_ms,
                status_code=s.status_code,
                logs=s.logs,
                attributes=s.attributes,
                trace_id=s.trace_id,
            )
            for s in spans
        ]


# =============================================================================
# Service Map
# =============================================================================


@router.get("/services")
@traced
async def get_service_map(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Get service dependency map."""
    # Default time range: last 1 hour
    if not from_date:
        from_date = datetime.now(timezone.utc) - timedelta(hours=1)
    if not to_date:
        to_date = datetime.now(timezone.utc)

    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        # Get all unique services
        result = await session.execute(
            select(Span.service_name)
            .where(
                and_(
                    Span.start_time >= from_date,
                    Span.start_time <= to_date,
                )
            )
            .distinct()
        )
        services = [row[0] for row in result]

        # Get service relationships (parent-child from spans)
        relationships = []
        result = await session.execute(
            select(Span.service_name, Span.parent_span_id)
            .where(
                and_(
                    Span.start_time >= from_date,
                    Span.start_time <= to_date,
                    Span.parent_span_id.isnot(None),
                )
            )
            .distinct()
        )

        # This is simplified - in production would analyze trace structure
        return {
            "services": [{"name": s, "type": "service"} for s in services],
            "relationships": relationships,
        }


# =============================================================================
# Trace Analysis
# =============================================================================


@router.post("/analyze")
@traced
async def analyze_trace(
    trace_id: str,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Analyze a trace to identify issues."""
    # Get trace details
    trace_detail = await get_trace(trace_id, tenant_id)

    # Analyze spans for issues
    issues = []
    slow_spans = []
    error_spans = []

    for span in trace_detail.spans:
        if span.duration_ms and span.duration_ms > 1000:
            slow_spans.append({
                "span_id": span.span_id,
                "operation": span.operation_name,
                "service": span.service_name,
                "duration_ms": span.duration_ms,
            })

        if span.status_code and span.status_code >= 400:
            error_spans.append({
                "span_id": span.span_id,
                "operation": span.operation_name,
                "service": span.service_name,
                "status_code": span.status_code,
                "message": span.status_message,
            })

    if slow_spans:
        issues.append({
            "type": "slow_spans",
            "count": len(slow_spans),
            "spans": slow_spans[:5],
        })

    if error_spans:
        issues.append({
            "type": "error_spans",
            "count": len(error_spans),
            "spans": error_spans[:5],
        })

    return {
        "trace_id": trace_id,
        "duration_ms": trace_detail.duration_ms,
        "span_count": trace_detail.total_spans,
        "service_count": len(trace_detail.services),
        "issues": issues,
        "services": trace_detail.services,
    }


# =============================================================================
# Traces for Incidents
# =============================================================================


@router.get("/incident/{incident_id}")
@traced
async def get_traces_for_incident(
    incident_id: str,
    time_range: str = Query("1h"),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Get traces relevant to an incident."""
    # Parse time range
    import re
    time_match = re.match(r"(\d+)([smhd])", time_range)
    if time_match:
        value, unit = time_match.groups()
        delta = int(value) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        from_date = datetime.now(timezone.utc) - timedelta(seconds=delta)
    else:
        from_date = datetime.now(timezone.utc) - timedelta(hours=1)

    to_date = datetime.now(timezone.utc)

    # Get error traces
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(Trace)
            .where(
                and_(
                    Trace.tenant_id == tenant_id,
                    Trace.start_time >= from_date,
                    Trace.start_time <= to_date,
                    Trace.status_code >= 400,
                )
            )
            .order_by(Trace.start_time.desc())
            .limit(50)
        )
        error_traces = list(result.scalars().all())

    return {
        "incident_id": incident_id,
        "error_traces": [
            {
                "trace_id": t.trace_id,
                "service_name": t.service_name,
                "operation_name": t.operation_name,
                "start_time": t.start_time.isoformat(),
                "duration_ms": t.duration_ms,
                "status_code": t.status_code,
            }
            for t in error_traces
        ],
        "total": len(error_traces),
    }


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Trace Correlation",
        description="Distributed trace ingestion and correlation",
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
        "sentinelai.trace_correlation.main:app",
        host="0.0.0.0",
        port=8005,
        reload=settings.app_debug,
    )
