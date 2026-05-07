"""SentinelAI Metrics Processing Service.

Handles metrics ingestion, aggregation, time-series queries,
and integration with anomaly detection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
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
    Metric,
    MetricAnomaly,
    MetricType,
    generate_uuid,
)
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("metrics-processing")
init_tracing("metrics-processing")

router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])


# =============================================================================
# Request/Response Models
# =============================================================================


class MetricIngestRequest(BaseModel):
    """Metric ingestion request."""
    metrics: list[dict[str, Any]] = Field(..., min_length=1, max_length=1000)
    tenant_id: str


class MetricDataPoint(BaseModel):
    """Single metric data point."""
    name: str = Field(..., min_length=1)
    value: float
    timestamp: datetime | None = None
    labels: dict[str, Any] = {}
    metric_type: MetricType = MetricType.GAUGE
    unit: str | None = None


class MetricQueryRequest(BaseModel):
    """Metric query request."""
    name: str
    labels: dict[str, Any] = {}
    from_date: datetime | None = None
    to_date: datetime | None = None
    aggregation: str = "avg"  # avg, sum, min, max, count
    interval: str = "5m"  # 1m, 5m, 15m, 1h, 1d


class MetricResponse(BaseModel):
    """Metric response."""
    name: str
    value: float
    timestamp: datetime
    labels: dict[str, Any]
    metric_type: str
    unit: str | None

    class Config:
        from_attributes = True


class TimeSeriesResponse(BaseModel):
    """Time series response."""
    name: str
    labels: dict[str, Any]
    points: list[dict[str, Any]]


class AggregationResponse(BaseModel):
    """Aggregation response."""
    name: str
    value: float
    labels: dict[str, Any]
    from_date: datetime
    to_date: datetime


# =============================================================================
# Metrics Ingestion
# =============================================================================


@router.post("/ingest")
@traced
async def ingest_metrics(
    request: MetricIngestRequest,
) -> dict[str, Any]:
    """Ingest metrics for processing."""
    ingested = 0
    failed = 0

    async with db_manager.session() as session:
        for metric_data in request.metrics:
            try:
                metric = Metric(
                    id=generate_uuid(),
                    name=metric_data.get("name"),
                    value=metric_data.get("value"),
                    timestamp=metric_data.get("timestamp", datetime.now(timezone.utc)),
                    metric_type=MetricType(metric_data.get("metric_type", "gauge")),
                    unit=metric_data.get("unit"),
                    labels=metric_data.get("labels", {}),
                    service_id=metric_data.get("service_id"),
                    tenant_id=request.tenant_id,
                )
                session.add(metric)
                ingested += 1

            except Exception as e:
                logger.error(f"Failed to parse metric: {e}")
                failed += 1

        await session.commit()

    metrics.queue_messages_processed.labels(
        queue="metrics_ingest",
        topic="metrics",
        status="success" if failed == 0 else "error",
    ).inc(ingested)

    return {
        "ingested": ingested,
        "failed": failed,
    }


@router.post("/batch")
@traced
async def batch_ingest_metrics(
    request: MetricIngestRequest,
) -> dict[str, Any]:
    """Batch ingest metrics (optimized for high throughput)."""
    # This would use ClickHouse for high-throughput ingestion
    return await ingest_metrics(request)


# =============================================================================
# Metrics Query
# =============================================================================


@router.get("/{metric_name}")
@traced
async def get_metric(
    metric_name: str,
    service_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    tenant_id: str = Query(...),
) -> list[MetricResponse]:
    """Get metric data points."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        # Default time range: last 1 hour
        if not from_date:
            from_date = datetime.now(timezone.utc) - timedelta(hours=1)
        if not to_date:
            to_date = datetime.now(timezone.utc)

        query = select(Metric).where(
            and_(
                Metric.name == metric_name,
                Metric.tenant_id == tenant_id,
                Metric.timestamp >= from_date,
                Metric.timestamp <= to_date,
            )
        )

        if service_id:
            query = query.where(Metric.service_id == service_id)

        query = query.order_by(Metric.timestamp.desc()).limit(1000)

        result = await session.execute(query)
        return list(result.scalars().all())


@router.post("/query")
@traced
async def query_metrics(
    request: MetricQueryRequest,
    tenant_id: str = Query(...),
) -> TimeSeriesResponse:
    """Query metrics with time range and aggregation."""
    # Default time range: last 1 hour
    if not request.from_date:
        request.from_date = datetime.now(timezone.utc) - timedelta(hours=1)
    if not request.to_date:
        request.to_date = datetime.now(timezone.utc)

    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select

        # Build base query
        query = select(Metric).where(
            and_(
                Metric.name == request.name,
                Metric.tenant_id == tenant_id,
                Metric.timestamp >= request.from_date,
                Metric.timestamp <= request.to_date,
            )
        )

        # Add label filters
        for key, value in request.labels.items():
            query = query.where(Metric.labels[key].astext == value)

        query = query.order_by(Metric.timestamp.asc())

        result = await session.execute(query)
        metrics_data = list(result.scalars().all())

    # Aggregate data points
    points = []
    for m in metrics_data:
        points.append({
            "timestamp": m.timestamp.isoformat(),
            "value": m.value,
        })

    return TimeSeriesResponse(
        name=request.name,
        labels=request.labels,
        points=points,
    )


@router.post("/aggregate")
@traced
async def aggregate_metrics(
    request: MetricQueryRequest,
    tenant_id: str = Query(...),
) -> AggregationResponse:
    """Aggregate metrics over time range."""
    # Default time range: last 1 hour
    if not request.from_date:
        request.from_date = datetime.now(timezone.utc) - timedelta(hours=1)
    if not request.to_date:
        request.to_date = datetime.now(timezone.utc)

    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select

        # Determine aggregation function
        agg_func = {
            "avg": func.avg,
            "sum": func.sum,
            "min": func.min,
            "max": func.max,
            "count": func.count,
        }.get(request.aggregation, func.avg)

        # Build query
        query = select(
            agg_func(Metric.value).label("value")
        ).where(
            and_(
                Metric.name == request.name,
                Metric.tenant_id == tenant_id,
                Metric.timestamp >= request.from_date,
                Metric.timestamp <= request.to_date,
            )
        )

        # Add label filters
        for key, value in request.labels.items():
            query = query.where(Metric.labels[key].astext == value)

        result = await session.execute(query)
        row = result.one()

    return AggregationResponse(
        name=request.name,
        value=float(row.value or 0),
        labels=request.labels,
        from_date=request.from_date,
        to_date=request.to_date,
    )


# =============================================================================
# Anomaly Detection
# =============================================================================


@router.get("/anomalies")
@traced
async def list_anomalies(
    service_id: str | None = None,
    anomaly_type: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """List detected anomalies."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select

        # Default time range: last 24 hours
        if not from_date:
            from_date = datetime.now(timezone.utc) - timedelta(hours=24)
        if not to_date:
            to_date = datetime.now(timezone.utc)

        query = select(MetricAnomaly).where(
            and_(
                MetricAnomaly.tenant_id == tenant_id,
                MetricAnomaly.timestamp >= from_date,
                MetricAnomaly.timestamp <= to_date,
            )
        )

        if service_id:
            query = query.where(MetricAnomaly.service_id == service_id)

        if anomaly_type:
            query = query.where(MetricAnomaly.anomaly_type == anomaly_type)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)

        # Apply pagination
        query = query.order_by(MetricAnomaly.timestamp.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await session.execute(query)
        anomalies = list(result.scalars().all())

        return {
            "anomalies": anomalies,
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/anomalies/{anomaly_id}")
@traced
async def get_anomaly(
    anomaly_id: str,
    tenant_id: str = Query(...),
) -> MetricAnomaly:
    """Get anomaly by ID."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(MetricAnomaly).where(
                and_(
                    MetricAnomaly.id == anomaly_id,
                    MetricAnomaly.tenant_id == tenant_id,
                )
            )
        )
        anomaly = result.scalar_one_or_none()

        if not anomaly:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Anomaly not found",
            )

        return anomaly


@router.post("/detect-anomalies")
@traced
async def trigger_anomaly_detection(
    service_id: str | None = None,
    metric_name: str | None = None,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Trigger anomaly detection for metrics."""
    # This would invoke the ML pipeline for anomaly detection
    return {
        "status": "triggered",
        "service_id": service_id,
        "metric_name": metric_name,
    }


# =============================================================================
# Metrics for Incidents
# =============================================================================


@router.get("/incident/{incident_id}")
@traced
async def get_metrics_for_incident(
    incident_id: str,
    time_range: str = Query("1h"),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Get relevant metrics for an incident."""
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

    # Get common metrics
    common_metrics = [
        "cpu_usage",
        "memory_usage",
        "disk_usage",
        "request_latency",
        "error_rate",
        "request_count",
    ]

    result = {}
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        for metric_name in common_metrics:
            query = select(Metric).where(
                and_(
                    Metric.name == metric_name,
                    Metric.tenant_id == tenant_id,
                    Metric.timestamp >= from_date,
                    Metric.timestamp <= to_date,
                )
            )

            if tenant_id:
                query = query.order_by(Metric.timestamp.desc()).limit(100)

            result[metric_name] = []

            try:
                res = await session.execute(query)
                metrics_data = list(res.scalars().all())
                for m in metrics_data:
                    result[metric_name].append({
                        "timestamp": m.timestamp.isoformat(),
                        "value": m.value,
                    })
            except Exception:
                pass

    return {
        "incident_id": incident_id,
        "metrics": result,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
    }


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Metrics Processing",
        description="Metrics ingestion, aggregation, and anomaly detection",
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
        "sentinelai.metrics_processing.main:app",
        host="0.0.0.0",
        port=8004,
        reload=settings.app_debug,
    )
