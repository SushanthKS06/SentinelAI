"""SentinelAI Core Models.

This module defines all database models for the SentinelAI platform.
Models are organized by domain and include proper indexes for performance.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinelai.database import Base, TimestampMixin


# =============================================================================
# Enums
# =============================================================================


class IncidentSeverity(str, Enum):
    """Incident severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IncidentStatus(str, Enum):
    """Incident status values."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    IDENTIFIED = "identified"
    MONITORING = "monitoring"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentSource(str, Enum):
    """Incident source types."""

    ALERT = "alert"
    ANOMALY = "anomaly"
    MANUAL = "manual"
    EXTERNAL = "external"
    SCHEDULED = "scheduled"


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertState(str, Enum):
    """Alert state values."""

    FIRING = "firing"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"
    ACKNOWLEDGED = "acknowledged"


class MetricType(str, Enum):
    """Metric types."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"
    UNKNOWN = "unknown"


class LogLevel(str, Enum):
    """Log levels."""

    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class DeploymentStatus(str, Enum):
    """Deployment status values."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class RemediationStatus(str, Enum):
    """Remediation status values."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPLIED = "applied"
    FAILED = "failed"
    REJECTED = "rejected"
    PARTIAL = "partial"


class UserRole(str, Enum):
    """User role values."""

    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"


# =============================================================================
# User & Authentication Models
# =============================================================================


class User(Base, TimestampMixin):
    """User model for authentication and authorization."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole), nullable=False, default=UserRole.VIEWER
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    avatar_url: Mapped[str | None] = mapped_column(String(500))

    # Relationships
    incidents: Mapped[list[Incident]] = relationship(
        "Incident", back_populates="assignee", foreign_keys="Incident.assignee_id"
    )
    notifications: Mapped[list[UserNotification]] = relationship(
        "UserNotification", back_populates="user"
    )

    __table_args__ = (
        Index("ix_users_email_lower", "email", postgresql_using="btree"),
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("username", name="uq_users_username"),
    )


class APIKey(Base, TimestampMixin):
    """API key model for service authentication."""

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="api_keys")


class RefreshToken(Base, TimestampMixin):
    """Refresh token model for JWT authentication."""

    __tablename__ = "refresh_tokens"

    token: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="refresh_tokens")


# Add relationships to User model
User.api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
User.refresh_tokens = relationship(
    "RefreshToken", back_populates="user", cascade="all, delete-orphan"
)


# =============================================================================
# Tenant & Organization Models
# =============================================================================


class Tenant(Base, TimestampMixin):
    """Multi-tenant organization model."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, index=True
    )
    plan: Mapped[str] = mapped_column(String(50), default="free")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    users: Mapped[list[TenantUser]] = relationship(
        "TenantUser", back_populates="tenant"
    )
    services: Mapped[list[Service]] = relationship(
        "Service", back_populates="tenant"
    )
    incidents: Mapped[list[Incident]] = relationship(
        "Incident", back_populates="tenant"
    )


class TenantUser(Base, TimestampMixin):
    """Many-to-many relationship between users and tenants."""

    __tablename__ = "tenant_users"

    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole), nullable=False, default=UserRole.VIEWER
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="tenant_users")
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="tenant_users")


# Add relationships to User model
User.tenant_users = relationship(
    "TenantUser", back_populates="user", cascade="all, delete-orphan"
)


# =============================================================================
# Service & Infrastructure Models
# =============================================================================


class Service(Base, TimestampMixin):
    """Service/microservice model."""

    __tablename__ = "services"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(50), default="application")
    metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="services")
    incidents: Mapped[list[Incident]] = relationship(
        "Incident", back_populates="service"
    )
    deployments: Mapped[list[Deployment]] = relationship(
        "Deployment", back_populates="service"
    )
    alert_rules: Mapped[list[AlertRule]] = relationship(
        "AlertRule", back_populates="service"
    )

    __table_args__ = (
        Index("ix_services_tenant_name", "tenant_id", "name", unique=True),
    )


class Environment(Base, TimestampMixin):
    """Deployment environment model."""

    __tablename__ = "environments"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_production: Mapped[bool] = mapped_column(Boolean, default=False)

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    deployments: Mapped[list[Deployment]] = relationship(
        "Deployment", back_populates="environment"
    )


# =============================================================================
# Incident Models
# =============================================================================


class Incident(Base, TimestampMixin):
    """Incident model - core entity for the platform."""

    __tablename__ = "incidents"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[IncidentSeverity] = mapped_column(
        SQLEnum(IncidentSeverity), nullable=False, index=True
    )
    status: Mapped[IncidentStatus] = mapped_column(
        SQLEnum(IncidentStatus), nullable=False, default=IncidentStatus.OPEN, index=True
    )
    source: Mapped[IncidentSource] = mapped_column(
        SQLEnum(IncidentSource), nullable=False, default=IncidentSource.ALERT
    )
    external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ttd_minutes: Mapped[int | None] = mapped_column(Integer)  # Time to detect
    ttr_minutes: Mapped[int | None] = mapped_column(Integer)  # Time to resolve

    # AI-generated fields
    summary: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    impact: Mapped[str | None] = mapped_column(Text)
    remediation: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[float | None] = mapped_column(Float)

    # Timeline data
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Metadata
    metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    labels: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    # Foreign keys
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    service_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("services.id", ondelete="SET NULL")
    )
    assignee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL")
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="incidents")
    service: Mapped[Service | None] = relationship("Service", back_populates="incidents")
    assignee: Mapped[User | None] = relationship(
        "User", back_populates="incidents", foreign_keys=[assignee_id]
    )
    alerts: Mapped[list[IncidentAlert]] = relationship(
        "IncidentAlert", back_populates="incident"
    )
    timeline_events: Mapped[list[IncidentTimelineEvent]] = relationship(
        "IncidentTimelineEvent", back_populates="incident"
    )
    comments: Mapped[list[IncidentComment]] = relationship(
        "IncidentComment", back_populates="incident"
    )

    __table_args__ = (
        Index("ix_incidents_tenant_status", "tenant_id", "status"),
        Index("ix_incidents_tenant_severity", "tenant_id", "severity"),
        Index("ix_incidents_tenant_service", "tenant_id", "service_id"),
        Index("ix_incidents_started_ended", "started_at", "ended_at"),
    )


class IncidentTimelineEvent(Base, TimestampMixin):
    """Timeline event for incident tracking."""

    __tablename__ = "incident_timeline_events"

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))

    # Relationships
    incident: Mapped[Incident] = relationship(
        "Incident", back_populates="timeline_events"
    )

    __table_args__ = (
        Index("ix_timeline_incident_timestamp", "incident_id", "timestamp"),
    )


class IncidentComment(Base, TimestampMixin):
    """Comment on an incident."""

    __tablename__ = "incident_comments"

    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    incident: Mapped[Incident] = relationship("Incident", back_populates="comments")


class IncidentAlert(Base, TimestampMixin):
    """Many-to-many relationship between incidents and alerts."""

    __tablename__ = "incident_alerts"

    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )
    alert_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    incident: Mapped[Incident] = relationship(
        "Incident", back_populates="alerts"
    )
    alert: Mapped[Alert] = relationship("Alert", back_populates="incidents")

    __table_args__ = (
        UniqueConstraint("incident_id", "alert_id", name="uq_incident_alert"),
    )


# =============================================================================
# Alert Models
# =============================================================================


class AlertRule(Base, TimestampMixin):
    """Alert rule configuration."""

    __tablename__ = "alert_rules"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        SQLEnum(AlertSeverity), nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Scheduling
    schedule: Mapped[str | None] = mapped_column(String(255))
    notification_channels: Mapped[list[str]] = mapped_column(ARRAY(String))

    service_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("services.id", ondelete="CASCADE")
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    service: Mapped[Service | None] = relationship("Service", back_populates="alert_rules")
    alerts: Mapped[list[Alert]] = relationship("Alert", back_populates="rule")

    __table_args__ = (
        Index("ix_alert_rules_tenant_enabled", "tenant_id", "is_enabled"),
    )


class Alert(Base, TimestampMixin):
    """Alert instance."""

    __tablename__ = "alerts"

    fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    state: Mapped[AlertState] = mapped_column(
        SQLEnum(AlertState), nullable=False, default=AlertState.FIRING
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        SQLEnum(AlertSeverity), nullable=False
    )
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    annotations: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    generator_url: Mapped[str | None] = mapped_column(String(500))

    # Deduplication
    deduplication_key: Mapped[str | None] = mapped_column(String(255), index=True)
    group_key: Mapped[str | None] = mapped_column(String(255), index=True)

    # Foreign keys
    rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("alert_rules.id", ondelete="SET NULL")
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    rule: Mapped[AlertRule | None] = relationship("AlertRule", back_populates="alerts")
    incidents: Mapped[list[IncidentAlert]] = relationship(
        "IncidentAlert", back_populates="alert"
    )

    __table_args__ = (
        Index("ix_alerts_tenant_state", "tenant_id", "state"),
        Index("ix_alerts_tenant_fingerprint", "tenant_id", "fingerprint"),
        Index("ix_alerts_tenant_group_key", "tenant_id", "group_key"),
    )


# =============================================================================
# Deployment Models
# =============================================================================


class Deployment(Base, TimestampMixin):
    """Deployment tracking model."""

    __tablename__ = "deployments"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[DeploymentStatus] = mapped_column(
        SQLEnum(DeploymentStatus), nullable=False, default=DeploymentStatus.PENDING
    )
    environment: Mapped[str] = mapped_column(String(50), nullable=False)
    revision: Mapped[str | None] = mapped_column(String(100))
    commit_sha: Mapped[str | None] = mapped_column(String(40), index=True)
    commit_message: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255))
    diff_url: Mapped[str | None] = mapped_column(String(500))
    metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)

    service_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    environment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("environments.id", ondelete="SET NULL")
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    service: Mapped[Service] = relationship("Service", back_populates="deployments")
    environment_rel: Mapped[Environment | None] = relationship(
        "Environment", back_populates="deployments"
    )

    __table_args__ = (
        Index("ix_deployments_tenant_service", "tenant_id", "service_id"),
        Index("ix_deployments_tenant_status", "tenant_id", "status"),
        Index("ix_deployments_started_at", "started_at"),
    )


# =============================================================================
# Metric Models
# =============================================================================


class Metric(Base, TimestampMixin):
    """Metric data model for time-series data in ClickHouse."""

    __tablename__ = "metrics"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    metric_type: Mapped[MetricType] = mapped_column(
        SQLEnum(MetricType), nullable=False, default=MetricType.GAUGE
    )
    unit: Mapped[str | None] = mapped_column(String(50))
    labels: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    service_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("services.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_metrics_name_timestamp", "name", "timestamp"),
        Index("ix_metrics_tenant_name_timestamp", "tenant_id", "name", "timestamp"),
        Index("ix_metrics_service_timestamp", "service_id", "timestamp"),
    )


class MetricAnomaly(Base, TimestampMixin):
    """Detected metric anomalies."""

    __tablename__ = "metric_anomalies"

    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    service_id: Mapped[str | None] = mapped_column(String(36), index=True)
    anomaly_type: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[float | None] = mapped_column(Float)
    deviation: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        Index("ix_anomalies_tenant_timestamp", "tenant_id", "timestamp"),
        Index("ix_anomalies_service_timestamp", "service_id", "timestamp"),
    )


# =============================================================================
# Log Models
# =============================================================================


class LogEntry(Base, TimestampMixin):
    """Log entry model for structured logging."""

    __tablename__ = "log_entries"

    message: Mapped[str] = mapped_column(Text, nullable=False)
    level: Mapped[LogLevel] = mapped_column(
        SQLEnum(LogLevel), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(36), index=True)
    span_id: Mapped[str | None] = mapped_column(String(16))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str | None] = mapped_column(String(255))
    hostname: Mapped[str | None] = mapped_column(String(255))

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_logs_tenant_timestamp", "tenant_id", "timestamp"),
        Index("ix_logs_tenant_service", "tenant_id", "service_name"),
        Index("ix_logs_trace_id", "trace_id"),
        Index("ix_logs_level_timestamp", "level", "timestamp"),
    )


class LogIndex(Base, TimestampMixin):
    """Log index configuration for efficient querying."""

    __tablename__ = "log_indexes"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    pattern: Mapped[str] = mapped_column(String(500), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )


# =============================================================================
# Trace Models
# =============================================================================


class Trace(Base, TimestampMixin):
    """Distributed trace model."""

    __tablename__ = "traces"

    trace_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, index=True
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    operation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    status_message: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        Index("ix_traces_tenant_service", "tenant_id", "service_name"),
        Index("ix_traces_tenant_time", "tenant_id", "start_time"),
    )


class Span(Base, TimestampMixin):
    """Span model for individual trace spans."""

    __tablename__ = "spans"

    span_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(16))
    operation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float | None] = mapped_column(Float)
    status_code: Mapped[int | None] = mapped_column(Integer)
    status_message: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    trace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("traces.trace_id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_spans_trace_id", "trace_id"),
        Index("ix_spans_service_time", "service_name", "start_time"),
    )


# =============================================================================
# Remediation Models
# =============================================================================


class Remediation(Base, TimestampMixin):
    """AI-generated remediation suggestions."""

    __tablename__ = "remediations"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[RemediationStatus] = mapped_column(
        SQLEnum(RemediationStatus), nullable=False, default=RemediationStatus.PENDING
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    tools: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    estimated_impact: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(50), default="medium")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))

    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        Index("ix_remediations_incident", "incident_id"),
    )


# =============================================================================
# Notification Models
# =============================================================================


class NotificationChannel(Base, TimestampMixin):
    """Notification channel configuration."""

    __tablename__ = "notification_channels"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # email, slack, etc.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )


class UserNotification(Base, TimestampMixin):
    """User notification preferences and delivery status."""

    __tablename__ = "user_notifications"

    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(50), default="pending")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    incident_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("incidents.id", ondelete="CASCADE")
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="notifications")


# =============================================================================
# Analytics Models
# =============================================================================


class ReliabilityScore(Base, TimestampMixin):
    """Service reliability score tracking."""

    __tablename__ = "reliability_scores"

    score: Mapped[float] = mapped_column(Float, nullable=False)
    slo_compliance: Mapped[float] = mapped_column(Float)
    mttr_minutes: Mapped[float | None] = mapped_column(Float)
    error_budget_remaining: Mapped[float | None] = mapped_column(Float)
    incident_count: Mapped[int] = mapped_column(Integer, default=0)
    alert_count: Mapped[int] = mapped_column(Integer, default=0)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    service_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        Index("ix_reliability_service_period", "service_id", "period_start"),
    )


class SLOConfiguration(Base, TimestampMixin):
    """Service Level Objective configuration."""

    __tablename__ = "slo_configurations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target: Mapped[float] = mapped_column(Float, nullable=False)  # e.g., 99.9
    window_type: Mapped[str] = mapped_column(String(50), nullable=False)  # rolling, calendar
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)

    service_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )


# =============================================================================
# Audit & Security Models
# =============================================================================


class AuditLog(Base, TimestampMixin):
    """Audit log for security and compliance."""

    __tablename__ = "audit_logs"

    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_type: Mapped[str] = mapped_column(String(50), default="user")
    metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))

    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_audit_tenant_timestamp", "tenant_id", "created_at"),
        Index("ix_audit_actor", "actor_id", "created_at"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )


# =============================================================================
# Helper Functions
# =============================================================================


def generate_uuid() -> str:
    """Generate a new UUID."""
    return str(uuid.uuid4())


def generate_fingerprint(labels: dict[str, Any]) -> str:
    """Generate alert fingerprint from labels."""
    import hashlib
    import json

    # Sort keys for consistent hashing
    sorted_labels = json.dumps(labels, sort_keys=True)
    return hashlib.sha256(sorted_labels.encode()).hexdigest()[:32]
