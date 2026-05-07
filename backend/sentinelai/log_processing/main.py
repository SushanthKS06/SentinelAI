"""SentinelAI Log Processing Service.

Handles log ingestion, parsing, indexing, and intelligent search
with full-text and semantic search capabilities.
"""

from __future__ import annotations

import logging
import re
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
from pydantic import BaseModel, Field

from sentinelai.config import settings
from sentinelai.database import db_manager
from sentinelai.logging import get_logger, setup_logging
from sentinelai.metrics import metrics
from sentinelai.models import (
    LogEntry,
    LogIndex,
    LogLevel,
    generate_uuid,
)
from sentinelai.tracing import init_tracing, traced

logger = get_logger(__name__)
setup_logging("log-processing")
init_tracing("log-processing")

router = APIRouter(prefix="/api/v1/logs", tags=["Logs"])


# =============================================================================
# Log Parsing
# =============================================================================


class LogParser:
    """Parse various log formats."""

    # Common log patterns
    JSON_PATTERN = re.compile(r'^\s*\{.*\}\s*$')
    NGINX_PATTERN = re.compile(
        r'(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<timestamp>[^\]]+)\]\s+'
        r'"(?P<method>\S+)\s+(?P<path>\S+)\s+(?P<protocol>\S+)"\s+'
        r'(?P<status>\d+)\s+(?P<size>\d+)\s+'
        r'"(?P<referer>[^"]*)"\s+"(?P<user_agent>[^"]*)"'
    )
    SYSLOG_PATTERN = re.compile(
        r'(?P<timestamp>\w+\s+\d+\s+\d+:\d+:\d+)\s+'
        r'(?P<host>\S+)\s+(?P<process>\S+)\[(?P<pid>\d+)\]:\s+'
        r'(?P<message>.*)'
    )

    @classmethod
    def parse(cls, raw_log: str, format: str = "auto") -> dict[str, Any]:
        """Parse log line into structured data."""
        result = {
            "raw": raw_log,
            "timestamp": datetime.now(timezone.utc),
            "level": LogLevel.INFO,
            "message": raw_log,
            "attributes": {},
        }

        if format == "json" or cls.JSON_PATTERN.match(raw_log):
            try:
                import json
                data = json.loads(raw_log)
                result["message"] = data.get("message", raw_log)
                result["level"] = LogLevel(data.get("level", "info").upper())
                result["timestamp"] = datetime.fromisoformat(
                    data.get("timestamp", "").replace("Z", "+00:00")
                ) if data.get("timestamp") else datetime.now(timezone.utc)
                result["attributes"] = {k: v for k, v in data.items()
                                       if k not in ("message", "level", "timestamp")}
            except Exception:
                result["message"] = raw_log
        elif format == "nginx":
            match = cls.NGINX_PATTERN.match(raw_log)
            if match:
                result["message"] = f"{match.group('method')} {match.group('path')}"
                result["level"] = LogLevel.INFO
                result["attributes"] = match.groupdict()
        else:
            # Try to detect level from message
            raw_upper = raw_log.upper()
            if "ERROR" in raw_upper or "FATAL" in raw_upper:
                result["level"] = LogLevel.ERROR
            elif "WARN" in raw_upper:
                result["level"] = LogLevel.WARNING
            elif "DEBUG" in raw_upper:
                result["level"] = LogLevel.DEBUG

        return result


# =============================================================================
# Request/Response Models
# =============================================================================


class LogIngestRequest(BaseModel):
    """Log ingestion request."""
    logs: list[dict[str, Any]] = Field(..., min_length=1, max_length=1000)
    service: str = Field(..., min_length=1)
    tenant_id: str
    timestamp: datetime | None = None


class LogSearchRequest(BaseModel):
    """Log search request."""
    query: str | None = None
    service: str | None = None
    level: LogLevel | None = None
    trace_id: str | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)


class LogResponse(BaseModel):
    """Log entry response."""
    id: str
    message: str
    level: str
    timestamp: datetime
    service_name: str
    trace_id: str | None
    span_id: str | None
    attributes: dict[str, Any]
    source: str | None

    class Config:
        from_attributes = True


# =============================================================================
# Log Ingestion
# =============================================================================


@router.post("/ingest")
@traced
async def ingest_logs(
    request: LogIngestRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Ingest logs for processing."""
    ingested = 0
    failed = 0

    async with db_manager.session() as session:
        for log_data in request.logs:
            try:
                # Parse log
                if isinstance(log_data, str):
                    parsed = LogParser.parse(log_data)
                else:
                    parsed = log_data

                log_entry = LogEntry(
                    id=generate_uuid(),
                    message=parsed.get("message", str(log_data)),
                    level=parsed.get("level", LogLevel.INFO),
                    timestamp=parsed.get("timestamp", datetime.now(timezone.utc)),
                    service_name=request.service,
                    trace_id=parsed.get("trace_id"),
                    span_id=parsed.get("span_id"),
                    attributes=parsed.get("attributes", {}),
                    source=parsed.get("source"),
                    tenant_id=request.tenant_id,
                )
                session.add(log_entry)
                ingested += 1

            except Exception as e:
                logger.error(f"Failed to parse log: {e}")
                failed += 1

        await session.commit()

    metrics.queue_messages_processed.labels(
        queue="log_ingest",
        topic="logs",
        status="success" if failed == 0 else "error",
    ).inc(ingested)

    return {
        "ingested": ingested,
        "failed": failed,
        "service": request.service,
    }


@router.post("/batch")
@traced
async def batch_ingest_logs(
    request: LogIngestRequest,
) -> dict[str, Any]:
    """Batch ingest logs (optimized for high throughput)."""
    # This would use ClickHouse for high-throughput ingestion
    # For now, use PostgreSQL
    return await ingest_logs(request, BackgroundTasks())


# =============================================================================
# Log Search
# =============================================================================


@router.post("/search")
@traced
async def search_logs(
    request: LogSearchRequest,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Search logs with filtering."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, func, select, or_

        # Build query
        query = select(LogEntry).where(LogEntry.tenant_id == tenant_id)

        if request.query:
            # Full-text search on message
            query = query.where(
                LogEntry.message.ilike(f"%{request.query}%")
            )

        if request.service:
            query = query.where(LogEntry.service_name == request.service)

        if request.level:
            query = query.where(LogEntry.level == request.level)

        if request.trace_id:
            query = query.where(LogEntry.trace_id == request.trace_id)

        if request.from_date:
            query = query.where(LogEntry.timestamp >= request.from_date)

        if request.to_date:
            query = query.where(LogEntry.timestamp <= request.to_date)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)

        # Apply pagination
        query = query.order_by(LogEntry.timestamp.desc())
        query = query.offset((request.page - 1) * request.page_size)
        query = query.limit(request.page_size)

        result = await session.execute(query)
        logs = list(result.scalars().all())

        return {
            "logs": logs,
            "total": total,
            "page": request.page,
            "page_size": request.page_size,
            "has_next": (request.page * request.page_size) < total,
        }


@router.get("")
@traced
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    service: str | None = None,
    level: LogLevel | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """List logs with filtering."""
    return await search_logs(
        LogSearchRequest(
            page=page,
            page_size=page_size,
            service=service,
            level=level,
            from_date=from_date,
            to_date=to_date,
        ),
        tenant_id,
    )


@router.get("/{log_id}")
@traced
async def get_log(log_id: str, tenant_id: str = Query(...)) -> LogResponse:
    """Get log by ID."""
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        result = await session.execute(
            select(LogEntry).where(
                and_(
                    LogEntry.id == log_id,
                    LogEntry.tenant_id == tenant_id,
                )
            )
        )
        log = result.scalar_one_or_none()

        if not log:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Log not found",
            )

        return log


# =============================================================================
# Log Streaming (WebSocket)
# =============================================================================


class LogStreamManager:
    """Manage WebSocket connections for log streaming."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.subscriptions: dict[str, set[str]] = {}  # client_id -> services

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.subscriptions[client_id] = set()
        metrics.active_connections.labels(service="log_stream").inc()

    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            del self.subscriptions[client_id]
            metrics.active_connections.labels(service="log_stream").dec()

    async def subscribe(self, client_id: str, services: list[str]):
        if client_id in self.subscriptions:
            self.subscriptions[client_id].update(services)

    async def stream_log(self, log: LogEntry):
        """Stream log to subscribed clients."""
        message = {
            "id": log.id,
            "message": log.message,
            "level": log.level.value,
            "timestamp": log.timestamp.isoformat(),
            "service_name": log.service_name,
            "trace_id": log.trace_id,
        }

        for client_id, services in self.subscriptions.items():
            if log.service_name in services or not services:
                if client_id in self.active_connections:
                    try:
                        await self.active_connections[client_id].send_json(message)
                    except Exception:
                        pass


log_stream_manager = LogStreamManager()


@router.websocket("/stream")
async def stream_logs_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time log streaming."""
    import uuid
    client_id = str(uuid.uuid4())

    try:
        await log_stream_manager.connect(websocket, client_id)

        while True:
            data = await websocket.receive_text()
            import json
            message = json.loads(data)

            if message.get("action") == "subscribe":
                services = message.get("services", [])
                await log_stream_manager.subscribe(client_id, services)
                await websocket.send_json({"status": "subscribed", "services": services})

    except WebSocketDisconnect:
        log_stream_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        log_stream_manager.disconnect(client_id)


# =============================================================================
# Log Index Management
# =============================================================================


class IndexCreateRequest(BaseModel):
    """Create log index request."""
    name: str = Field(..., min_length=1, max_length=255)
    pattern: str = Field(..., min_length=1, max_length=500)
    retention_days: int = Field(30, ge=1, le=365)


@router.post("/indexes", status_code=status.HTTP_201_CREATED)
@traced
async def create_log_index(
    request: IndexCreateRequest,
    tenant_id: str = Query(...),
) -> LogIndex:
    """Create a log index."""
    async with db_manager.session() as session:
        index = LogIndex(
            id=generate_uuid(),
            name=request.name,
            pattern=request.pattern,
            retention_days=request.retention_days,
            tenant_id=tenant_id,
        )
        session.add(index)
        await session.commit()
        await session.refresh(index)
        return index


@router.get("/indexes")
@traced
async def list_log_indexes(tenant_id: str = Query(...)) -> list[LogIndex]:
    """List log indexes."""
    async with db_manager.session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(LogIndex)
            .where(LogIndex.tenant_id == tenant_id)
            .order_by(LogIndex.created_at.desc())
        )
        return list(result.scalars().all())


# =============================================================================
# Log Intelligence
# =============================================================================


@router.post("/analyze")
@traced
async def analyze_logs(
    query: str = Query(...),
    service: str | None = None,
    time_range: str = Query("1h"),
    tenant_id: str = Query(...),
) -> dict[str, Any]:
    """Analyze logs using AI to find patterns and anomalies."""
    # Parse time range
    from dateutil import parser
    import re

    time_match = re.match(r"(\d+)([smhd])", time_range)
    if time_match:
        value, unit = time_match.groups()
        delta = int(value) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        from_date = datetime.now(timezone.utc) - timedelta(seconds=delta)
    else:
        from_date = datetime.now(timezone.utc) - timedelta(hours=1)

    # Get logs for analysis
    async with db_manager.session() as session:
        from sqlalchemy import and_, select

        query_stmt = select(LogEntry).where(
            and_(
                LogEntry.tenant_id == tenant_id,
                LogEntry.timestamp >= from_date,
            )
        )

        if service:
            query_stmt = query_stmt.where(LogEntry.service_name == service)

        query_stmt = query_stmt.order_by(LogEntry.timestamp.desc()).limit(1000)

        result = await session.execute(query_stmt)
        logs = list(result.scalars().all())

    # This would call the AI service for analysis
    return {
        "query": query,
        "logs_analyzed": len(logs),
        "patterns": [],
        "anomalies": [],
        "summary": "Analysis would be performed by AI service",
    }


# =============================================================================
# Application Factory
# =============================================================================


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    from fastapi import FastAPI as FastAPIBase
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPIBase(
        title="SentinelAI Log Processing",
        description="Log ingestion, parsing, and intelligent search",
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
        "sentinelai.log_processing.main:app",
        host="0.0.0.0",
        port=8003,
        reload=settings.app_debug,
    )
