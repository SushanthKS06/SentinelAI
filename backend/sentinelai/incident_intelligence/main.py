"""SentinelAI Incident Intelligence Service.

Handles incident lifecycle management, timeline tracking,
AI-powered RCA, and remediation suggestions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
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
    Incident,
    IncidentComment,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    IncidentTimelineEvent,
    Remediation,
    RemediationStatus,
    User,
    generate_uuid,
)
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("incident-intelligence")
init_tracing("incident-intelligence")

router = APIRouter(prefix="/api/v1/incidents", tags=["Incidents"])


# =============================================================================
# Request/Response Models
# =============================================================================


class IncidentCreateRequest(BaseModel):
    """Create incident request."""
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    severity: IncidentSeverity
    source: IncidentSource = IncidentSource.MANUAL
    service_id: str | None = None
    labels: list[str] = []
    metadata: dict[str, Any] = {}


class IncidentUpdateRequest(BaseModel):
    """Update incident request."""
    title: str | None = None
    description: str | None = None
    severity: IncidentSeverity | None = None
    status: IncidentStatus | None = None
    assignee_id: str | None = None
    labels: list[str] | None = None


class IncidentResponse(BaseModel):
    """Incident response."""
    id: str
    title: str
    description: str | None
    severity: str
    status: str
    source: str
    external_id: str | None
    started_at: datetime
    ended_at: datetime | None
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    ttd_minutes: int | None
    ttr_minutes: int | None
    summary: str | None
    root_cause: str | None
    impact: str | None
    remediation: str | None
    ai_confidence: float | None
    timeline: list[dict[str, Any]]
    metadata: dict[str, Any]
    labels: list[str]
    service_id: str | None
    assignee_id: str | None
    tenant_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TimelineEventCreate(BaseModel):
    """Create timeline event request."""
    event_type: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    metadata: dict[str, Any] = {}


class CommentCreate(BaseModel):
    """Create comment request."""
    content: str = Field(..., min_length=1)
    is_internal: bool = False


class RemediationResponse(BaseModel):
    """Remediation response."""
    id: str
    title: str
    description: str
    steps: list[dict[str, Any]]
    status: str
    confidence: float
    category: str | None
    tools: list[str]
    estimated_impact: str | None
    risk_level: str
    created_at: datetime

    class Config:
        from_attributes = True


# =============================================================================
# Incident CRUD Operations
# =============================================================================


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
@traced
async def create_incident(
    request: IncidentCreateRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Query(...),
) -> IncidentResponse:
    """Create a new incident."""
    async with db_manager.session() as session:
        from sqlalchemy import select

        incident = Incident(
            id=generate_uuid(),
            title=request.title,
            description=request.description,
            severity=request.severity,
            status=IncidentStatus.OPEN,
            source=request.source,
            started_at=datetime.now(timezone.utc),
            timeline=[],
            metadata=request.metadata,
            labels=request.labels,
            service_id=request.service_id,
            assignee_id=None,
            tenant_id=tenant_id,
        )
        session.add(incident)

        # Add initial timeline event
        timeline_event = IncidentTimelineEvent(
            id=generate_uuid(),
            event_type="created",
            description=f"Incident created by {current_user.username}",
            timestamp=datetime.now(timezone.utc),
            incident_id=incident.id,
            actor_id=current_user.id,
        )
        session.add(timeline_event)

        await session.commit()
        await session.refresh(incident)

        metrics.incidents_total.labels(
            severity=request.severity.value,
            status="open",
            source=request.source.value,
        ).inc()

        return incident


@router.get("", response_model=dict)
@traced
async def list_incidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    severity: IncidentSeverity | None = None,
    status: IncidentStatus | None = None,
    service_id: str | None = None,
    assignee_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """List incidents with filtering and pagination."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select

        # Build query
        query = select(Incident).where(Incident.tenant_id == tenant_id)

        if severity:
            query = query.where(Incident.severity == severity)
        if status:
            query = query.where(Incident.status == status)
        if service_id:
            query = query.where(Incident.service_id == service_id)
        if assignee_id:
            query = query.where(Incident.assignee_id == assignee_id)
        if from_date:
            query = query.where(Incident.started_at >= from_date)
        if to_date:
            query = query.where(Incident.started_at <= to_date)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)

        # Apply pagination
        query = query.order_by(Incident.started_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await session.execute(query)
        incidents = list(result.scalars().all())

        return {
            "incidents": incidents,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_next": (page * page_size) < total,
            "has_prev": page > 1,
        }


@router.get("/{incident_id}", response_model=IncidentResponse)
@traced
async def get_incident(
    incident_id: str,
    tenant_id: str = Query(...),
) -> IncidentResponse:
    """Get incident by ID."""
    async with db_manager.session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(Incident).where(
                and_(
                    Incident.id == incident_id,
                    Incident.tenant_id == tenant_id,
                )
            )
        )
        incident = result.scalar_one_or_none()

        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )

        return incident


@router.patch("/{incident_id}", response_model=IncidentResponse)
@traced
async def update_incident(
    incident_id: str,
    request: IncidentUpdateRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Query(...),
) -> IncidentResponse:
    """Update incident."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(Incident).where(
                and_(
                    Incident.id == incident_id,
                    Incident.tenant_id == tenant_id,
                )
            )
        )
        incident = result.scalar_one_or_none()

        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )

        # Track status changes for timeline
        old_status = incident.status

        # Update fields
        if request.title is not None:
            incident.title = request.title
        if request.description is not None:
            incident.description = request.description
        if request.severity is not None:
            incident.severity = request.severity
        if request.status is not None:
            incident.status = request.status
            if request.status == IncidentStatus.RESOLVED:
                incident.resolved_at = datetime.now(timezone.utc)
                if incident.started_at:
                    ttr = (incident.resolved_at - incident.started_at).total_seconds() / 60
                    incident.ttr_minutes = int(ttr)
        if request.assignee_id is not None:
            incident.assignee_id = request.assignee_id
        if request.labels is not None:
            incident.labels = request.labels

        # Add timeline event for status change
        if request.status and request.status != old_status:
            timeline_event = IncidentTimelineEvent(
                id=generate_uuid(),
                event_type="status_changed",
                description=f"Status changed from {old_status.value} to {request.status.value}",
                timestamp=datetime.now(timezone.utc),
                incident_id=incident.id,
                actor_id=current_user.id,
            )
            session.add(timeline_event)

        await session.commit()
        await session.refresh(incident)

        return incident


@router.post("/{incident_id}/acknowledge", response_model=IncidentResponse)
@traced
async def acknowledge_incident(
    incident_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Query(...),
) -> IncidentResponse:
    """Acknowledge an incident."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(Incident).where(
                and_(
                    Incident.id == incident_id,
                    Incident.tenant_id == tenant_id,
                )
            )
        )
        incident = result.scalar_one_or_none()

        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )

        if incident.status == IncidentStatus.OPEN:
            incident.status = IncidentStatus.INVESTIGATING
            incident.acknowledged_at = datetime.now(timezone.utc)
            if incident.started_at:
                ttd = (incident.acknowledged_at - incident.started_at).total_seconds() / 60
                incident.ttd_minutes = int(ttd)

        # Add timeline event
        timeline_event = IncidentTimelineEvent(
            id=generate_uuid(),
            event_type="acknowledged",
            description=f"Incident acknowledged by {current_user.username}",
            timestamp=datetime.now(timezone.utc),
            incident_id=incident.id,
            actor_id=current_user.id,
        )
        session.add(timeline_event)

        await session.commit()
        await session.refresh(incident)

        return incident


@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
@traced
async def resolve_incident(
    incident_id: str,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Query(...),
) -> IncidentResponse:
    """Resolve an incident."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(Incident).where(
                and_(
                    Incident.id == incident_id,
                    Incident.tenant_id == tenant_id,
                )
            )
        )
        incident = result.scalar_one_or_none()

        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )

        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = datetime.now(timezone.utc)
        incident.ended_at = datetime.now(timezone.utc)

        if incident.started_at:
            ttr = (incident.resolved_at - incident.started_at).total_seconds() / 60
            incident.ttr_minutes = int(ttr)

        # Add timeline event
        timeline_event = IncidentTimelineEvent(
            id=generate_uuid(),
            event_type="resolved",
            description=f"Incident resolved by {current_user.username}",
            timestamp=datetime.now(timezone.utc),
            incident_id=incident.id,
            actor_id=current_user.id,
        )
        session.add(timeline_event)

        await session.commit()
        await session.refresh(incident)

        metrics.incidents_total.labels(
            severity=incident.severity.value,
            status="resolved",
            source=incident.source.value,
        ).inc()

        return incident


# =============================================================================
# Timeline & Comments
# =============================================================================


@router.get("/{incident_id}/timeline")
@traced
async def get_incident_timeline(
    incident_id: str,
    tenant_id: str = Query(...),
) -> list[IncidentTimelineEvent]:
    """Get incident timeline events."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(IncidentTimelineEvent)
            .where(IncidentTimelineEvent.incident_id == incident_id)
            .order_by(IncidentTimelineEvent.timestamp.asc())
        )
        return list(result.scalars().all())


@router.post("/{incident_id}/timeline", status_code=status.HTTP_201_CREATED)
@traced
async def add_timeline_event(
    incident_id: str,
    request: TimelineEventCreate,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Query(...),
) -> IncidentTimelineEvent:
    """Add a timeline event to an incident."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        # Verify incident exists
        result = await session.execute(
            select(Incident).where(
                and_(
                    Incident.id == incident_id,
                    Incident.tenant_id == tenant_id,
                )
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )

        event = IncidentTimelineEvent(
            id=generate_uuid(),
            event_type=request.event_type,
            description=request.description,
            metadata=request.metadata,
            timestamp=datetime.now(timezone.utc),
            incident_id=incident_id,
            actor_id=current_user.id,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        return event


@router.get("/{incident_id}/comments")
@traced
async def get_incident_comments(
    incident_id: str,
    tenant_id: str = Query(...),
) -> list[IncidentComment]:
    """Get incident comments."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(IncidentComment)
            .where(IncidentComment.incident_id == incident_id)
            .order_by(IncidentComment.created_at.desc())
        )
        return list(result.scalars().all())


@router.post("/{incident_id}/comments", status_code=status.HTTP_201_CREATED)
@traced
async def add_comment(
    incident_id: str,
    request: CommentCreate,
    current_user: User = Depends(get_current_user),
    tenant_id: str = Query(...),
) -> IncidentComment:
    """Add a comment to an incident."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        # Verify incident exists
        result = await session.execute(
            select(Incident).where(
                and_(
                    Incident.id == incident_id,
                    Incident.tenant_id == tenant_id,
                )
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )

        comment = IncidentComment(
            id=generate_uuid(),
            content=request.content,
            is_internal=request.is_internal,
            incident_id=incident_id,
            author_id=current_user.id,
        )
        session.add(comment)
        await session.commit()
        await session.refresh(comment)

        return comment


# =============================================================================
# AI-Powered Features
# =============================================================================


@router.post("/{incident_id}/remediation")
@traced
async def get_remediation_suggestions(
    incident_id: str,
    tenant_id: str = Query(...),
) -> list[RemediationResponse]:
    """Get AI-generated remediation suggestions."""
    # This would integrate with the AI orchestration service
    # For now, return placeholder
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(Remediation)
            .where(Remediation.incident_id == incident_id)
            .order_by(Remediation.confidence.desc())
        )
        return list(result.scalars().all())


@router.post("/{incident_id}/summarize")
@traced
async def summarize_incident(
    incident_id: str,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Generate AI-powered incident summary."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(Incident).where(
                and_(
                    Incident.id == incident_id,
                    Incident.tenant_id == tenant_id,
                )
            )
        )
        incident = result.scalar_one_or_none()

        if not incident:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Incident not found",
            )

        # This would call the AI service to generate summary
        # For now, return existing summary or placeholder
        return {
            "summary": incident.summary or "Summary not available",
            "root_cause": incident.root_cause or "Root cause not identified",
            "impact": incident.impact or "Impact not analyzed",
            "remediation": incident.remediation or "Remediation not available",
            "confidence": incident.ai_confidence or 0.0,
        }


@router.post("/{incident_id}/analyze")
@traced
async def analyze_incident(
    incident_id: str,
    include_logs: bool = True,
    include_traces: bool = True,
    include_metrics: bool = True,
    include_deployments: bool = True,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Run AI investigation on an incident."""
    # This would orchestrate the multi-agent system
    # to analyze the incident from multiple angles
    return {
        "incident_id": incident_id,
        "status": "investigation_started",
        "phases": [
            "log_analysis" if include_logs else None,
            "trace_analysis" if include_traces else None,
            "metrics_analysis" if include_metrics else None,
            "deployment_analysis" if include_deployments else None,
        ],
    }


# =============================================================================
# Dependencies
# =============================================================================

async def get_current_user() -> User:
    """Get current user (placeholder - would use auth service)."""
    return User(
        id="placeholder",
        email="placeholder@example.com",
        username="placeholder",
        hashed_password="",
        role="admin",
        is_active=True,
    )


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Incident Intelligence",
        description="Incident management and AI-powered RCA",
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
        "sentinelai.incident_intelligence.main:app",
        host="0.0.0.0",
        port=8002,
        reload=settings.app_debug,
    )
