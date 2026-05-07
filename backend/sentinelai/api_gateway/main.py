"""SentinelAI API Gateway Service.

The API Gateway serves as the single entry point for all client requests.
It handles authentication, rate limiting, request routing, caching,
and service orchestration.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from starlette.middleware.base import BaseHTTPMiddleware

from sentinelai.config import settings
from sentinelai.database import db_manager
from sentinelai.logging import (
    CorrelationContext,
    generate_correlation_id,
    get_logger,
    setup_logging,
)
from sentinelai.metrics import get_metrics, get_metrics_content_type, metrics
from sentinelai.tracing import init_tracing, instrument_fastapi

# Initialize logging and tracing
logger = setup_logging("api-gateway")
init_tracing("api-gateway")


# =============================================================================
# Middleware
# =============================================================================


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for request/response logging with correlation IDs."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # Generate correlation ID
        correlation_id = request.headers.get("X-Correlation-ID") or generate_correlation_id()
        request.state.correlation_id = correlation_id

        # Track request
        start_time = time.perf_counter()

        # Process request with correlation context
        with CorrelationContext(correlation_id=correlation_id):
            response = await call_next(request)

        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id

        # Track metrics
        duration = time.perf_counter() - start_time
        metrics.requests_total.labels(
            method=request.method,
            endpoint=request.url.path,
            status=str(response.status_code),
        ).inc()
        metrics.request_duration.labels(
            method=request.method,
            endpoint=request.url.path,
        ).observe(duration)

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware for rate limiting requests."""

    def __init__(self, app: Any, redis_client: Any = None):
        super().__init__(app)
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Simple rate limiting (would use Redis in production)
        client_ip = request.client.host if request.client else "unknown"
        # Implementation would check Redis for rate limit
        return await call_next(request)


# =============================================================================
# Request/Response Models
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = settings.app_version
    timestamp: str = Field(default_factory=lambda: str(time.time()))


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    detail: str | None = None
    correlation_id: str | None = None


class PaginatedResponse(BaseModel):
    """Paginated response wrapper."""
    data: list[Any]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


# =============================================================================
# API Routers (placeholder imports)
# =============================================================================

# These would be imported from their respective services
# from sentinelai.auth_service.routers import router as auth_router
# from sentinelai.incident_intelligence.routers import router as incidents_router
# from sentinelai.log_processing.routers import router as logs_router
# from sentinelai.metrics_processing.routers import router as metrics_router
# from sentinelai.trace_correlation.routers import router as traces_router
# from sentinelai.ai_orchestration.routers import router as ai_router


# =============================================================================
# Application Factory
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Application lifespan manager."""
    # Startup
    logger.info("Starting SentinelAI API Gateway")
    metrics.service_info.info({
        "name": "api-gateway",
        "version": settings.app_version,
        "environment": settings.app_env,
    })

    # Initialize database
    try:
        db_manager.create_engine()
        logger.info("Database connection established")
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")

    yield

    # Shutdown
    logger.info("Shutting down SentinelAI API Gateway")
    await db_manager.dispose()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="SentinelAI API",
        description="Autonomous AI Reliability Engineer API",
        version=settings.app_version,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Add middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(RequestLoggingMiddleware)
    if settings.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware)

    # Instrument FastAPI
    instrument_fastapi(app)

    # Include routers
    app.include_router(router, prefix="/api/v1")
    app.include_router(health_router, tags=["Health"])
    app.include_router(metrics_router, tags=["Metrics"])

    return app


# =============================================================================
# API Routes
# =============================================================================

router = APIRouter(prefix="/api/v1")


@router.get("/health")
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
    )


# =============================================================================
# Health Router
# =============================================================================

health_router = APIRouter()


@health_router.get("/health")
async def health() -> HealthResponse:
    """Basic health check."""
    return HealthResponse()


@health_router.get("/health/ready")
async def readiness() -> HealthResponse:
    """Readiness check - verifies all dependencies."""
    checks = {
        "database": False,
        "redis": False,
        "kafka": False,
    }

    # Check database
    try:
        async with db_manager.session() as session:
            await session.execute("SELECT 1")
        checks["database"] = True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")

    # Check Redis
    # try:
    #     redis = await get_redis()
    #     await redis.ping()
    #     checks["redis"] = True
    # except Exception as e:
    #     logger.error(f"Redis health check failed: {e}")

    # Check Kafka
    # try:
    #     # Check Kafka connectivity
    #     checks["kafka"] = True
    # except Exception as e:
    #     logger.error(f"Kafka health check failed: {e}")

    all_healthy = all(checks.values())
    return HealthResponse(
        status="ready" if all_healthy else "degraded",
    )


@health_router.get("/health/live")
async def liveness() -> HealthResponse:
    """Liveness check - verifies the service is running."""
    return HealthResponse()


# =============================================================================
# Metrics Router
# =============================================================================

metrics_router = APIRouter()


@metrics_router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(
        content=get_metrics(),
        media_type=get_metrics_content_type(),
    )


# =============================================================================
# Authentication Endpoints
# =============================================================================

auth_router = APIRouter()


class LoginRequest(BaseModel):
    """Login request."""
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Login response."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RegisterRequest(BaseModel):
    """Registration request."""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
    full_name: str | None = None


class RefreshTokenRequest(BaseModel):
    """Token refresh request."""
    refresh_token: str


@auth_router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """Authenticate user and return tokens."""
    # Implementation would validate credentials and generate JWT
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Authentication not implemented",
    )


@auth_router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest) -> dict[str, str]:
    """Register a new user."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Registration not implemented",
    )


@auth_router.post("/auth/refresh", response_model=LoginResponse)
async def refresh_token(request: RefreshTokenRequest) -> LoginResponse:
    """Refresh access token."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Token refresh not implemented",
    )


@auth_router.post("/auth/logout")
async def logout(authorization: str = Header(None)) -> dict[str, str]:
    """Logout user and revoke tokens."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Logout not implemented",
    )


# =============================================================================
# Incident Endpoints
# =============================================================================

incidents_router = APIRouter()


class IncidentCreateRequest(BaseModel):
    """Create incident request."""
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = None
    severity: str = Field(..., pattern="^(critical|high|medium|low|info)$")
    source: str = Field(..., pattern="^(alert|anomaly|manual|external|scheduled)$")
    service_id: str | None = None
    labels: list[str] = []


class IncidentResponse(BaseModel):
    """Incident response."""
    id: str
    title: str
    description: str | None
    severity: str
    status: str
    source: str
    started_at: str
    ended_at: str | None
    summary: str | None
    root_cause: str | None
    remediation: str | None
    service_id: str | None
    assignee_id: str | None
    created_at: str
    updated_at: str


class IncidentListResponse(BaseModel):
    """List incidents response."""
    incidents: list[IncidentResponse]
    total: int
    page: int
    page_size: int


@incidents_router.get("/incidents", response_model=IncidentListResponse)
async def list_incidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    service_id: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
) -> IncidentListResponse:
    """List all incidents with filtering and pagination."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.get("/incidents/{incident_id}", response_model=IncidentResponse)
async def get_incident(incident_id: str) -> IncidentResponse:
    """Get incident by ID."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.post("/incidents", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(request: IncidentCreateRequest) -> IncidentResponse:
    """Create a new incident."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.patch("/incidents/{incident_id}", response_model=IncidentResponse)
async def update_incident(
    incident_id: str,
    status: str | None = None,
    assignee_id: str | None = None,
    severity: str | None = None,
) -> IncidentResponse:
    """Update incident."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.post("/incidents/{incident_id}/acknowledge")
async def acknowledge_incident(incident_id: str) -> IncidentResponse:
    """Acknowledge an incident."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: str) -> IncidentResponse:
    """Resolve an incident."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.get("/incidents/{incident_id}/timeline")
async def get_incident_timeline(incident_id: str) -> list[dict[str, Any]]:
    """Get incident timeline events."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.get("/incidents/{incident_id}/alerts")
async def get_incident_alerts(incident_id: str) -> list[dict[str, Any]]:
    """Get alerts associated with an incident."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.get("/incidents/{incident_id}/traces")
async def get_incident_traces(incident_id: str) -> list[dict[str, Any]]:
    """Get traces associated with an incident."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.get("/incidents/{incident_id}/logs")
async def get_incident_logs(
    incident_id: str,
    limit: int = Query(100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Get logs associated with an incident."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Incidents not implemented",
    )


@incidents_router.post("/incidents/{incident_id}/remediation")
async def get_remediation_suggestions(incident_id: str) -> dict[str, Any]:
    """Get AI-generated remediation suggestions."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="AI remediation not implemented",
    )


@incidents_router.post("/incidents/{incident_id}/summarize")
async def summarize_incident(incident_id: str) -> dict[str, Any]:
    """Generate AI-powered incident summary."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="AI summarization not implemented",
    )


# =============================================================================
# Alert Endpoints
# =============================================================================

alerts_router = APIRouter()


class AlertResponse(BaseModel):
    """Alert response."""
    id: str
    fingerprint: str
    state: str
    severity: str
    labels: dict[str, Any]
    annotations: dict[str, Any]
    starts_at: str
    ends_at: str | None
    rule_id: str | None


@alerts_router.get("/alerts")
async def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    state: str | None = Query(None),
    severity: str | None = Query(None),
    service_id: str | None = Query(None),
) -> dict[str, Any]:
    """List all alerts."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Alerts not implemented",
    )


@alerts_router.get("/alerts/{alert_id}")
async def get_alert(alert_id: str) -> AlertResponse:
    """Get alert by ID."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Alerts not implemented",
    )


@alerts_router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str) -> AlertResponse:
    """Acknowledge an alert."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Alerts not implemented",
    )


# =============================================================================
# Service Endpoints
# =============================================================================

services_router = APIRouter()


class ServiceResponse(BaseModel):
    """Service response."""
    id: str
    name: str
    description: str | None
    type: str
    metadata: dict[str, Any]
    tags: list[str]
    created_at: str


@services_router.get("/services")
async def list_services(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """List all services."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Services not implemented",
    )


@services_router.get("/services/{service_id}")
async def get_service(service_id: str) -> ServiceResponse:
    """Get service by ID."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Services not implemented",
    )


# =============================================================================
# Metrics Endpoints
# =============================================================================

metrics_api_router = APIRouter()


@metrics_api_router.get("/metrics")
async def get_metrics_data(
    name: str = Query(...),
    service_id: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    interval: str = Query("5m"),
) -> dict[str, Any]:
    """Get time-series metrics data."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Metrics not implemented",
    )


@metrics_api_router.get("/metrics/aggregate")
async def get_metrics_aggregate(
    name: str = Query(...),
    aggregation: str = Query("avg"),
    service_id: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
) -> dict[str, Any]:
    """Get aggregated metrics."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Metrics not implemented",
    )


# =============================================================================
# Logs Endpoints
# =============================================================================

logs_router = APIRouter()


@logs_router.get("/logs")
async def search_logs(
    query: str | None = Query(None),
    service: str | None = Query(None),
    level: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Search and filter logs."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Logs not implemented",
    )


@logs_router.get("/logs/stream")
async def stream_logs(
    service: str | None = Query(None),
    level: str | None = Query(None),
) -> StreamingResponse:
    """Stream logs in real-time."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Log streaming not implemented",
    )


# =============================================================================
# Traces Endpoints
# =============================================================================

traces_router = APIRouter()


@traces_router.get("/traces")
async def search_traces(
    service: str | None = Query(None),
    operation: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Search and filter traces."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Traces not implemented",
    )


@traces_router.get("/traces/{trace_id}")
async def get_trace(trace_id: str) -> dict[str, Any]:
    """Get trace by ID with all spans."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Traces not implemented",
    )


# =============================================================================
# Deployment Endpoints
# =============================================================================

deployments_router = APIRouter()


@deployments_router.get("/deployments")
async def list_deployments(
    service_id: str | None = Query(None),
    environment: str | None = Query(None),
    status: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """List deployments."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Deployments not implemented",
    )


@deployments_router.get("/deployments/{deployment_id}")
async def get_deployment(deployment_id: str) -> dict[str, Any]:
    """Get deployment by ID."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Deployments not implemented",
    )


# =============================================================================
# Anomaly Endpoints
# =============================================================================

anomalies_router = APIRouter()


@anomalies_router.get("/anomalies")
async def list_anomalies(
    service_id: str | None = Query(None),
    type: str | None = Query(None),
    severity: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """List detected anomalies."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Anomalies not implemented",
    )


@anomalies_router.get("/anomalies/{anomaly_id}")
async def get_anomaly(anomaly_id: str) -> dict[str, Any]:
    """Get anomaly by ID."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Anomalies not implemented",
    )


# =============================================================================
# Analytics Endpoints
# =============================================================================

analytics_router = APIRouter()


@analytics_router.get("/analytics/reliability")
async def get_reliability_scores(
    service_id: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
) -> dict[str, Any]:
    """Get reliability scores over time."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Analytics not implemented",
    )


@analytics_router.get("/analytics/slo")
async def get_slo_status(
    service_id: str | None = Query(None),
) -> dict[str, Any]:
    """Get SLO compliance status."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Analytics not implemented",
    )


@analytics_router.get("/analytics/mttr")
async def get_mttr_analysis(
    service_id: str | None = Query(None),
    from_date: str | None = Query(None),
    to_date: str | None = Query(None),
) -> dict[str, Any]:
    """Get MTTR analysis."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Analytics not implemented",
    )


# =============================================================================
# AI Investigation Endpoints
# =============================================================================

ai_router = APIRouter()


@ai_router.post("/investigate")
async def investigate_incident(
    incident_id: str,
    include_logs: bool = True,
    include_traces: bool = True,
    include_metrics: bool = True,
    include_deployments: bool = True,
) -> dict[str, Any]:
    """Run AI investigation on an incident."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="AI investigation not implemented",
    )


@ai_router.post("/analyze-logs")
async def analyze_logs(
    query: str,
    time_range: str = "1h",
    service: str | None = None,
) -> dict[str, Any]:
    """Analyze logs using AI."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Log analysis not implemented",
    )


@ai_router.post("/analyze-metrics")
async def analyze_metrics(
    metric_name: str,
    service_id: str | None = None,
    time_range: str = "1h",
) -> dict[str, Any]:
    """Analyze metrics using AI."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Metric analysis not implemented",
    )


@ai_router.post("/correlate")
async def correlate_events(
    incident_id: str,
    time_range: str = "1h",
) -> dict[str, Any]:
    """Correlate events across logs, metrics, and traces."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Event correlation not implemented",
    )


# =============================================================================
# WebSocket Endpoint
# =============================================================================

class ConnectionManager:
    """WebSocket connection manager."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: str):
        """Accept and store WebSocket connection."""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        metrics.active_connections.labels(service="websocket").inc()

    def disconnect(self, client_id: str):
        """Remove WebSocket connection."""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            metrics.active_connections.labels(service="websocket").dec()

    async def send_message(self, client_id: str, message: dict[str, Any]):
        """Send message to specific client."""
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)

    async def broadcast(self, message: dict[str, Any]):
        """Broadcast message to all clients."""
        for connection in self.active_connections.values():
            await connection.send_json(message)


ws_manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    client_id = None
    try:
        # Extract client ID from query params
        await websocket.accept()
        # For now, generate a simple client ID
        import uuid
        client_id = str(uuid.uuid4())
        await ws_manager.connect(websocket, client_id)

        while True:
            # Keep connection alive and handle messages
            data = await websocket.receive_text()
            # Process message (e.g., subscribe to specific events)
            await websocket.send_json({"status": "connected", "client_id": client_id})

    except WebSocketDisconnect:
        if client_id:
            ws_manager.disconnect(client_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        if client_id:
            ws_manager.disconnect(client_id)


# Include all routers
app = create_app()
app.include_router(auth_router, prefix="/api/v1", tags=["Authentication"])
app.include_router(incidents_router, prefix="/api/v1", tags=["Incidents"])
app.include_router(alerts_router, prefix="/api/v1", tags=["Alerts"])
app.include_router(services_router, prefix="/api/v1", tags=["Services"])
app.include_router(metrics_api_router, prefix="/api/v1", tags=["Metrics"])
app.include_router(logs_router, prefix="/api/v1", tags=["Logs"])
app.include_router(traces_router, prefix="/api/v1", tags=["Traces"])
app.include_router(deployments_router, prefix="/api/v1", tags=["Deployments"])
app.include_router(anomalies_router, prefix="/api/v1", tags=["Anomalies"])
app.include_router(analytics_router, prefix="/api/v1", tags=["Analytics"])
app.include_router(ai_router, prefix="/api/v1", tags=["AI Investigation"])


# Main entry point
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "sentinelai.api_gateway.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.app_debug,
        log_level=settings.log_level.lower(),
    )
