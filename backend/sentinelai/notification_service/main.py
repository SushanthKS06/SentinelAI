"""SentinelAI Notification Service.

Handles alert notifications via email, Slack, PagerDuty, Discord,
and other notification channels.
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
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("notification-service")
init_tracing("notification-service")

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


# =============================================================================
# Notification Clients
# =============================================================================


class EmailNotifier:
    """Send notifications via email."""

    async def send(
        self,
        to: list[str],
        subject: str,
        body: str,
    ) -> dict[str, Any]:
        if not settings.notification_email_enabled:
            return {"status": "disabled"}

        # Implementation would use SMTP
        logger.info(f"Sending email to {to}: {subject}")
        return {"status": "sent", "recipients": len(to)}


class SlackNotifier:
    """Send notifications via Slack."""

    async def send(
        self,
        channel: str,
        message: str,
        severity: str = "info",
    ) -> dict[str, Any]:
        if not settings.notification_slack_enabled:
            return {"status": "disabled"}

        # Implementation would use Slack Webhook
        logger.info(f"Sending Slack message to {channel}: {message}")
        return {"status": "sent"}


class PagerDutyNotifier:
    """Send notifications via PagerDuty."""

    async def send(
        self,
        title: str,
        description: str,
        severity: str,
        incident_id: str,
    ) -> dict[str, Any]:
        if not settings.notification_pagerduty_enabled:
            return {"status": "disabled"}

        # Implementation would use PagerDuty API
        logger.info(f"Creating PagerDuty incident: {title}")
        return {"status": "created", "incident_id": incident_id}


class DiscordNotifier:
    """Send notifications via Discord."""

    async def send(
        self,
        message: str,
        embed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not settings.notification_discord_enabled:
            return {"status": "disabled"}

        # Implementation would use Discord Webhook
        logger.info(f"Sending Discord message")
        return {"status": "sent"}


# Global notifiers
email_notifier = EmailNotifier()
slack_notifier = SlackNotifier()
pagerduty_notifier = PagerDutyNotifier()
discord_notifier = DiscordNotifier()


# =============================================================================
# Request/Response Models
# =============================================================================


class NotificationRequest(BaseModel):
    """Send notification request."""
    channel: str = Field(..., pattern="^(email|slack|pagerduty|discord)$")
    recipients: list[str] | None = None
    subject: str | None = None
    message: str = Field(..., min_length=1)
    severity: str = "info"
    incident_id: str | None = None


class NotificationResponse(BaseModel):
    """Notification response."""
    status: str
    channel: str
    sent_at: datetime


class NotificationChannelCreate(BaseModel):
    """Create notification channel."""
    name: str = Field(..., min_length=1)
    type: str = Field(..., pattern="^(email|slack|pagerduty|discord)$")
    config: dict[str, Any]


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/send")
@traced
async def send_notification(
    request: NotificationRequest,
) -> NotificationResponse:
    """Send a notification."""
    if request.channel == "email":
        if not request.recipients:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Recipients required for email",
            )
        result = await email_notifier.send(
            to=request.recipients,
            subject=request.subject or "SentinelAI Notification",
            body=request.message,
        )
    elif request.channel == "slack":
        result = await slack_notifier.send(
            channel=settings.notification_slack_channel,
            message=request.message,
            severity=request.severity,
        )
    elif request.channel == "pagerduty":
        if not request.incident_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incident ID required for PagerDuty",
            )
        result = await pagerduty_notifier.send(
            title=request.subject or "SentinelAI Alert",
            description=request.message,
            severity=request.severity,
            incident_id=request.incident_id,
        )
    elif request.channel == "discord":
        result = await discord_notifier.send(
            message=request.message,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid channel",
        )

    return NotificationResponse(
        status=result.get("status", "sent"),
        channel=request.channel,
        sent_at=datetime.now(timezone.utc),
    )


@router.post("/incidents/{incident_id}/notify")
@traced
async def notify_incident(
    incident_id: str,
    channels: list[str] = Query(...),
    message: str = Query(...),
) -> dict[str, Any]:
    """Notify about an incident across multiple channels."""
    results = []

    if "email" in channels:
        results.append(await email_notifier.send(
            to=["oncall@example.com"],
            subject=f"Incident: {incident_id}",
            body=message,
        ))

    if "slack" in channels:
        results.append(await slack_notifier.send(
            channel=settings.notification_slack_channel,
            message=message,
        ))

    if "pagerduty" in channels:
        results.append(await pagerduty_notifier.send(
            title=f"Incident: {incident_id}",
            description=message,
            severity="critical",
            incident_id=incident_id,
        ))

    return {"incident_id": incident_id, "results": results}


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Notification Service",
        description="Alert notification service",
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
        "sentinelai.notification_service.main:app",
        host="0.0.0.0",
        port=8008,
        reload=settings.app_debug,
    )
