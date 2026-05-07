"""SentinelAI Analytics Service.

Provides reliability analytics, SLO tracking, MTTR analysis,
and comprehensive reporting.
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
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("analytics-service")
init_tracing("analytics-service")

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


# =============================================================================
# Request/Response Models
# =============================================================================


class ReliabilityScoreResponse(BaseModel):
    """Reliability score response."""
    service_id: str
    score: float
    slo_compliance: float
    mttr_minutes: float
    error_budget_remaining: float
    incident_count: int
    alert_count: int
    period_start: datetime
    period_end: datetime


class MTTRAnalysisResponse(BaseModel):
    """MTTR analysis response."""
    service_id: str
    avg_mttr_minutes: float
    min_mttr_minutes: float
    max_mttr_minutes: float
    mttr_trend: str
    incidents_analyzed: int


class SLOStatusResponse(BaseModel):
    """SLO status response."""
    slo_id: str
    name: str
    target: float
    current: float
    status: str
    error_budget_remaining: float
    period_remaining: str


class IncidentTrendResponse(BaseModel):
    """Incident trend response."""
    period: str
    total_incidents: int
    critical: int
    high: int
    medium: int
    low: int
    mttr_avg: float


# =============================================================================
# Analytics Endpoints
# =============================================================================


@router.get("/reliability/{service_id}")
@traced
async def get_reliability_score(
    service_id: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    tenant_id: str = Query(...),
) -> ReliabilityScoreResponse:
    """Get reliability score for a service."""
    # Default time range: last 30 days
    if not from_date:
        from_date = datetime.now(timezone.utc) - timedelta(days=30)
    if not to_date:
        to_date = datetime.now(timezone.utc)

    # Calculate metrics from database
    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select
        from sentinelai.models import Incident, Alert, ReliabilityScore

        # Get incidents
        result = await session.execute(
            select(
                func.count(Incident.id).label("count"),
                func.avg(Incident.ttr_minutes).label("avg_ttr"),
            ).where(
                and_(
                    Incident.service_id == service_id,
                    Incident.tenant_id == tenant_id,
                    Incident.started_at >= from_date,
                    Incident.started_at <= to_date,
                    Incident.ttr_minutes.isnot(None),
                )
            )
        )
        row = result.one()

        # Get alerts
        result = await session.execute(
            select(func.count(Alert.id)).where(
                and_(
                    Alert.tenant_id == tenant_id,
                    Alert.starts_at >= from_date,
                    Alert.starts_at <= to_date,
                )
            )
        )
        alert_count = await session.scalar(result) or 0

        # Calculate score (simplified)
        incident_count = row.count or 0
        avg_ttr = float(row.avg_ttr or 0)

        # Score based on incident count and MTTR
        score = max(0, 100 - (incident_count * 5) - (avg_ttr / 10))
        slo_compliance = 99.9 if score > 95 else 95.0 if score > 80 else 0.0

        return ReliabilityScoreResponse(
            service_id=service_id,
            score=score,
            slo_compliance=slo_compliance,
            mttr_minutes=avg_ttr,
            error_budget_remaining=max(0, 100 - (100 - slo_compliance) * 10),
            incident_count=incident_count,
            alert_count=alert_count,
            period_start=from_date,
            period_end=to_date,
        )


@router.get("/mttr/{service_id}")
@traced
async def get_mttr_analysis(
    service_id: str,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    tenant_id: str = Query(...),
) -> MTTRAnalysisResponse:
    """Get MTTR analysis for a service."""
    if not from_date:
        from_date = datetime.now(timezone.utc) - timedelta(days=30)
    if not to_date:
        to_date = datetime.now(timezone.utc)

    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select
        from sentinelai.models import Incident

        result = await session.execute(
            select(
                func.avg(Incident.ttr_minutes).label("avg"),
                func.min(Incident.ttr_minutes).label("min"),
                func.max(Incident.ttr_minutes).label("max"),
                func.count(Incident.id).label("count"),
            ).where(
                and_(
                    Incident.service_id == service_id,
                    Incident.tenant_id == tenant_id,
                    Incident.started_at >= from_date,
                    Incident.started_at <= to_date,
                    Incident.ttr_minutes.isnot(None),
                )
            )
        )
        row = result.one()

    return MTTRAnalysisResponse(
        service_id=service_id,
        avg_mttr_minutes=float(row.avg or 0),
        min_mttr_minutes=float(row.min or 0),
        max_mttr_minutes=float(row.max or 0),
        mttr_trend="improving" if (row.avg or 0) < 30 else "stable",
        incidents_analyzed=row.count or 0,
    )


@router.get("/slo/{service_id}")
@traced
async def get_slo_status(
    service_id: str,
    tenant_id: str = Query(...),
) -> list[SLOStatusResponse]:
    """Get SLO status for a service."""
    # This would query SLO configurations
    # For now, return sample data
    return [
        SLOStatusResponse(
            slo_id="slo-001",
            name="API Availability",
            target=99.9,
            current=99.95,
            status="healthy",
            error_budget_remaining=50.0,
            period_remaining="15 days",
        ),
        SLOStatusResponse(
            slo_id="slo-002",
            name="API Latency p99",
            target=200.0,
            current=180.0,
            status="healthy",
            error_budget_remaining=75.0,
            period_remaining="15 days",
        ),
    ]


@router.get("/incidents/trend")
@traced
async def get_incident_trend(
    period: str = Query("7d", pattern="^(7d|30d|90d)$"),
    service_id: str | None = None,
    tenant_id: str = Query(...),
) -> list[IncidentTrendResponse]:
    """Get incident trend over time."""
    # Parse period
    days = int(period.replace("d", ""))
    from_date = datetime.now(timezone.utc) - timedelta(days=days)

    # This would aggregate incidents by day
    return [
        IncidentTrendResponse(
            period="2024-01-01",
            total_incidents=5,
            critical=1,
            high=2,
            medium=1,
            low=1,
            mttr_avg=25.0,
        ),
    ]


@router.get("/summary")
@traced
async def get_analytics_summary(
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Get overall analytics summary."""
    if not from_date:
        from_date = datetime.now(timezone.utc) - timedelta(days=30)
    if not to_date:
        to_date = datetime.now(timezone.utc)

    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select
        from sentinelai.models import Incident, Alert

        # Incident stats
        result = await session.execute(
            select(
                func.count(Incident.id).label("total"),
                func.sum(
                    Incident.severity.in_(["critical", "high"])
                ).label("critical_high"),
                func.avg(Incident.ttr_minutes).label("avg_ttr"),
            ).where(
                and_(
                    Incident.tenant_id == tenant_id,
                    Incident.started_at >= from_date,
                    Incident.started_at <= to_date,
                )
            )
        )
        incident_row = result.one()

        # Alert stats
        result = await session.execute(
            select(func.count(Alert.id)).where(
                and_(
                    Alert.tenant_id == tenant_id,
                    Alert.starts_at >= from_date,
                    Alert.starts_at <= to_date,
                    Alert.state == "firing",
                )
            )
        )
        firing_alerts = await session.scalar(result) or 0

    return {
        "period": {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        },
        "incidents": {
            "total": incident_row.total or 0,
            "critical_high": incident_row.critical_high or 0,
            "avg_mttr_minutes": float(incident_row.avg_ttr or 0),
        },
        "alerts": {
            "firing": firing_alerts,
        },
        "reliability": {
            "avg_score": 95.5,
            "services_healthy": 8,
            "services_degraded": 2,
        },
    }


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Analytics Service",
        description="Reliability analytics and reporting",
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
        "sentinelai.analytics_service.main:app",
        host="0.0.0.0",
        port=8009,
        reload=settings.app_debug,
    )
