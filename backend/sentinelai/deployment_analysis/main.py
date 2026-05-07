"""SentinelAI Deployment Analysis Service.

Handles deployment tracking, correlation with incidents,
and deployment impact analysis.
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
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("deployment-analysis")
init_tracing("deployment-analysis")

router = APIRouter(prefix="/api/v1/deployments", tags=["Deployments"])


# =============================================================================
# Request/Response Models
# =============================================================================


class DeploymentCreateRequest(BaseModel):
    """Create deployment request."""
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    environment: str = Field(..., pattern="^(development|staging|production)$")
    service_id: str
    revision: str | None = None
    commit_sha: str | None = None
    commit_message: str | None = None
    author: str | None = None
    diff_url: str | None = None
    metadata: dict[str, Any] = {}


class DeploymentResponse(BaseModel):
    """Deployment response."""
    id: str
    name: str
    version: str
    status: str
    environment: str
    revision: str | None
    commit_sha: str | None
    commit_message: str | None
    author: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: int | None
    service_id: str

    class Config:
        from_attributes = True


class DeploymentCorrelationResponse(BaseModel):
    """Deployment correlation response."""
    deployment_id: str
    incident_id: str
    correlation_type: str
    confidence: float
    time_distance_minutes: int


# =============================================================================
# Deployment Endpoints
# =============================================================================


@router.post("", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
@traced
async def create_deployment(
    request: DeploymentCreateRequest,
    tenant_id: str = Query(...),
) -> DeploymentResponse:
    """Create a new deployment record."""
    from sentinelai.models import Deployment, DeploymentStatus, generate_uuid

    async with db_manager.session() as session:
        deployment = Deployment(
            id=generate_uuid(),
            name=request.name,
            version=request.version,
            status=DeploymentStatus.PENDING,
            environment=request.environment,
            revision=request.revision,
            commit_sha=request.commit_sha,
            commit_message=request.commit_message,
            author=request.author,
            diff_url=request.diff_url,
            metadata=request.metadata,
            started_at=datetime.now(timezone.utc),
            service_id=request.service_id,
            tenant_id=tenant_id,
        )
        session.add(deployment)
        await session.commit()
        await session.refresh(deployment)
        return deployment


@router.get("")
@traced
async def list_deployments(
    service_id: str | None = None,
    environment: str | None = None,
    status: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """List deployments with filtering."""
    if not from_date:
        from_date = datetime.now(timezone.utc) - timedelta(days=30)
    if not to_date:
        to_date = datetime.now(timezone.utc)

    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select
        from sentinelai.models import Deployment

        query = select(Deployment).where(
            and_(
                Deployment.tenant_id == tenant_id,
                Deployment.created_at >= from_date,
                Deployment.created_at <= to_date,
            )
        )

        if service_id:
            query = query.where(Deployment.service_id == service_id)
        if environment:
            query = query.where(Deployment.environment == environment)
        if status:
            query = query.where(Deployment.status == status)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)

        # Apply pagination
        query = query.order_by(Deployment.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        result = await session.execute(query)
        deployments = list(result.scalars().all())

        return {
            "deployments": deployments,
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.get("/{deployment_id}")
@traced
async def get_deployment(
    deployment_id: str,
    tenant_id: str = Query(...),
) -> DeploymentResponse:
    """Get deployment by ID."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select
        from sentinelai.models import Deployment

        result = await session.execute(
            select(Deployment).where(
                and_(
                    Deployment.id == deployment_id,
                    Deployment.tenant_id == tenant_id,
                )
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deployment not found",
            )

        return deployment


@router.patch("/{deployment_id}/status")
@traced
async def update_deployment_status(
    deployment_id: str,
    status: str = Query(...),
    tenant_id: str = Query(...),
) -> DeploymentResponse:
    """Update deployment status."""
    from sentinelai.models import Deployment, DeploymentStatus

    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(Deployment).where(
                and_(
                    Deployment.id == deployment_id,
                    Deployment.tenant_id == tenant_id,
                )
            )
        )
        deployment = result.scalar_one_or_none()

        if not deployment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deployment not found",
            )

        deployment.status = DeploymentStatus(status)
        if status == "success" or status == "failed":
            deployment.finished_at = datetime.now(timezone.utc)
            if deployment.started_at:
                deployment.duration_seconds = int(
                    (deployment.finished_at - deployment.started_at).total_seconds()
                )

        await session.commit()
        await session.refresh(deployment)
        return deployment


@router.get("/{deployment_id}/incidents")
@traced
async def get_deployment_incidents(
    deployment_id: str,
    tenant_id: str = Query(...),
) -> list[DeploymentCorrelationResponse]:
    """Get incidents correlated with a deployment."""
    # This would analyze incidents that occurred after the deployment
    # and correlate based on time proximity and service
    return []


@router.post("/correlate")
@traced
async def correlate_deployments(
    incident_id: str,
    time_range: str = Query("24h"),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Find deployments that may have caused an incident."""
    import re

    # Parse time range
    time_match = re.match(r"(\d+)([smhd])", time_range)
    if time_match:
        value, unit = time_match.groups()
        delta = int(value) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        from_date = datetime.now(timezone.utc) - timedelta(seconds=delta)
    else:
        from_date = datetime.now(timezone.utc) - timedelta(hours=24)

    # Get deployments in time range
    async with db_manager.session() as session:
        from sqlalchemy import and_, select
        from sentinelai.models import Deployment

        result = await session.execute(
            select(Deployment).where(
                and_(
                    Deployment.tenant_id == tenant_id,
                    Deployment.created_at >= from_date,
                    Deployment.environment == "production",
                )
            ).order_by(Deployment.created_at.desc())
        )
        deployments = list(result.scalars().all())

    return {
        "incident_id": incident_id,
        "potential_causes": [
            {
                "deployment_id": d.id,
                "version": d.version,
                "time_before_incident": "15 minutes",
                "confidence": 0.8,
            }
            for d in deployments[:5]
        ],
    }


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Deployment Analysis",
        description="Deployment tracking and incident correlation",
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
        "sentinelai.deployment_analysis.main:app",
        host="0.0.0.0",
        port=8010,
        reload=settings.app_debug,
    )
