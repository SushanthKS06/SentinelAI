"""SentinelAI Streaming Pipeline Service.

Handles real-time event streaming, WebSocket connections,
and SSE (Server-Sent Events) for live updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sentinelai.config import settings
from sentinelai.logging import get_logger, setup_logging
from sentinelai.metrics import metrics
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("streaming-pipeline")
init_tracing("streaming-pipeline")

router = APIRouter(prefix="/api/v1/stream", tags=["Streaming"])


# =============================================================================
# Event Types
# =============================================================================


class EventType:
    """Event type constants."""
    INCIDENT_CREATED = "incident.created"
    INCIDENT_UPDATED = "incident.updated"
    INCIDENT_RESOLVED = "incident.resolved"
    ALERT_FIRING = "alert.firing"
    ALERT_RESOLVED = "alert.resolved"
    ANOMALY_DETECTED = "anomaly.detected"
    DEPLOYMENT_STARTED = "deployment.started"
    DEPLOYMENT_COMPLETED = "deployment.completed"
    METRIC_THRESHOLD = "metric.threshold"
    TRACE_ERROR = "trace.error"


# =============================================================================
# Connection Manager
# =============================================================================


class ConnectionManager:
    """Manage WebSocket and SSE connections."""

    def __init__(self):
        self.websocket_connections: dict[str, WebSocket] = {}
        self.sse_connections: dict[str, asyncio.Queue] = {}
        self.subscriptions: dict[str, set[str]] = {}  # client_id -> event_types

    async def connect_websocket(self, websocket: WebSocket, client_id: str):
        """Accept and store WebSocket connection."""
        await websocket.accept()
        self.websocket_connections[client_id] = websocket
        self.subscriptions[client_id] = set()
        metrics.active_connections.labels(service="websocket").inc()
        logger.info(f"WebSocket connected: {client_id}")

    def disconnect_websocket(self, client_id: str):
        """Remove WebSocket connection."""
        if client_id in self.websocket_connections:
            del self.websocket_connections[client_id]
            metrics.active_connections.labels(service="websocket").dec()
            logger.info(f"WebSocket disconnected: {client_id}")

    async def connect_sse(self, client_id: str) -> asyncio.Queue:
        """Create and store SSE connection."""
        queue = asyncio.Queue(maxsize=100)
        self.sse_connections[client_id] = queue
        self.subscriptions[client_id] = set()
        metrics.active_connections.labels(service="sse").inc()
        logger.info(f"SSE connected: {client_id}")
        return queue

    def disconnect_sse(self, client_id: str):
        """Remove SSE connection."""
        if client_id in self.sse_connections:
            del self.sse_connections[client_id]
            metrics.active_connections.labels(service="sse").dec()
            logger.info(f"SSE disconnected: {client_id}")

    def subscribe(self, client_id: str, event_types: list[str]):
        """Subscribe client to event types."""
        if client_id in self.subscriptions:
            self.subscriptions[client_id].update(event_types)

    def unsubscribe(self, client_id: str, event_types: list[str]):
        """Unsubscribe client from event types."""
        if client_id in self.subscriptions:
            self.subscriptions[client_id].difference_update(event_types)

    async def broadcast_websocket(self, event_type: str, data: dict[str, Any]):
        """Broadcast to all subscribed WebSocket clients."""
        message = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        disconnected = []
        for client_id, websocket in self.websocket_connections.items():
            if not self.subscriptions[client_id] or event_type in self.subscriptions[client_id]:
                try:
                    await websocket.send_text(message)
                except Exception as e:
                    logger.error(f"Failed to send to {client_id}: {e}")
                    disconnected.append(client_id)

        for client_id in disconnected:
            self.disconnect_websocket(client_id)

    async def broadcast_sse(self, event_type: str, data: dict[str, Any]):
        """Broadcast to all subscribed SSE clients."""
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        disconnected = []
        for client_id, queue in self.sse_connections.items():
            if not self.subscriptions[client_id] or event_type in self.subscriptions[client_id]:
                try:
                    await queue.put(message)
                except Exception as e:
                    logger.error(f"Failed to queue for {client_id}: {e}")
                    disconnected.append(client_id)

        for client_id in disconnected:
            self.disconnect_sse(client_id)

    async def broadcast(self, event_type: str, data: dict[str, Any]):
        """Broadcast to all connections."""
        await self.broadcast_websocket(event_type, data)
        await self.broadcast_sse(event_type, data)


# Global connection manager
connection_manager = ConnectionManager()


# =============================================================================
# Request/Response Models
# =============================================================================


class EventPublishRequest(BaseModel):
    """Publish event request."""
    event_type: str = Field(..., min_length=1)
    data: dict[str, Any] = Field(..., min_length=1)
    source: str | None = None


class SubscriptionRequest(BaseModel):
    """Subscribe to events request."""
    event_types: list[str] = Field(..., min_length=1)


# =============================================================================
# API Endpoints
# =============================================================================


@router.websocket("/ws")
async def websocket_stream(websocket: WebSocket):
    """WebSocket endpoint for real-time streaming."""
    import uuid
    client_id = str(uuid.uuid4())

    try:
        await connection_manager.connect_websocket(websocket, client_id)

        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("action") == "subscribe":
                event_types = message.get("event_types", [])
                connection_manager.subscribe(client_id, event_types)
                await websocket.send_json({
                    "type": "subscribed",
                    "event_types": event_types,
                })
            elif message.get("action") == "unsubscribe":
                event_types = message.get("event_types", [])
                connection_manager.unsubscribe(client_id, event_types)
                await websocket.send_json({
                    "type": "unsubscribed",
                    "event_types": event_types,
                })

    except WebSocketDisconnect:
        connection_manager.disconnect_websocket(client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        connection_manager.disconnect_websocket(client_id)


@router.get("/sse")
async def sse_stream(
    event_types: str = Query(""),
):
    """SSE endpoint for server-sent events."""
    import uuid
    client_id = str(uuid.uuid4())

    async def event_generator():
        queue = await connection_manager.connect_sse(client_id)

        # Subscribe to events
        if event_types:
            types = event_types.split(",")
            connection_manager.subscribe(client_id, types)

        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
        except asyncio.CancelledError:
            connection_manager.disconnect_sse(client_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/publish")
@traced
async def publish_event(
    request: EventPublishRequest,
) -> dict[str, str]:
    """Publish an event to all subscribers."""
    await connection_manager.broadcast(request.event_type, request.data)

    metrics.queue_messages_processed.labels(
        queue="event_stream",
        topic=request.event_type,
        status="published",
    ).inc()

    return {
        "status": "published",
        "event_type": request.event_type,
    }


@router.post("/incidents/{incident_id}/stream")
@traced
async def stream_incident_updates(
    incident_id: str,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Start streaming incident updates."""
    # This would trigger a background task to stream updates
    return {
        "status": "streaming",
        "incident_id": incident_id,
    }


# =============================================================================
# Event Producers
# =============================================================================


async def produce_incident_created(incident: dict[str, Any]):
    """Produce incident created event."""
    await connection_manager.broadcast(
        EventType.INCIDENT_CREATED,
        incident,
    )


async def produce_alert_firing(alert: dict[str, Any]):
    """Produce alert firing event."""
    await connection_manager.broadcast(
        EventType.ALERT_FIRING,
        alert,
    )


async def produce_anomaly_detected(anomaly: dict[str, Any]):
    """Produce anomaly detected event."""
    await connection_manager.broadcast(
        EventType.ANOMALY_DETECTED,
        anomaly,
    )


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Streaming Pipeline",
        description="Real-time event streaming service",
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
        "sentinelai.streaming_pipeline.main:app",
        host="0.0.0.0",
        port=8012,
        reload=settings.app_debug,
    )
