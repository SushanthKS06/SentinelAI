"""SentinelAI Configuration Module.

This module provides centralized configuration management using Pydantic Settings.
All configuration is environment-driven with validation and type coercion.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

from pydantic import (
    AnyUrl,
    EmailStr,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SentinelAI Application Settings.

    All settings are loaded from environment variables with sensible defaults.
    The settings are validated at startup to catch configuration errors early.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =============================================================================
    # Application Configuration
    # =============================================================================
    app_name: str = Field(default="SentinelAI", description="Application name")
    app_env: Literal["development", "staging", "production"] = Field(
        default="development", description="Application environment"
    )
    app_version: str = Field(default="0.1.0", description="Application version")
    app_debug: bool = Field(default=False, description="Debug mode")
    app_host: str = Field(default="0.0.0.0", description="Host to bind to")
    app_port: int = Field(default=8000, description="Port to bind to")

    # =============================================================================
    # Database Configuration
    # =============================================================================
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_db: str = Field(default="sentinelai", description="PostgreSQL database")
    postgres_user: str = Field(default="sentinelai", description="PostgreSQL user")
    postgres_password: SecretStr = Field(
        default="changeme", description="PostgreSQL password"
    )
    postgres_pool_size: int = Field(default=20, description="Connection pool size")
    postgres_max_overflow: int = Field(
        default=10, description="Max connection overflow"
    )
    postgres_pool_timeout: int = Field(
        default=30, description="Connection pool timeout"
    )
    postgres_echo: bool = Field(default=False, description="Echo SQL queries")

    @property
    def database_url(self) -> str:
        """Generate PostgreSQL connection URL."""
        return PostgresDsn(
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Generate synchronous PostgreSQL connection URL."""
        return PostgresDsn(
            f"postgresql://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # =============================================================================
    # Redis Configuration
    # =============================================================================
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_db: int = Field(default=0, description="Redis database number")
    redis_password: SecretStr = Field(default="", description="Redis password")
    redis_max_connections: int = Field(
        default=50, description="Max Redis connections"
    )
    redis_ssl: bool = Field(default=False, description="Use SSL for Redis")

    @property
    def redis_url(self) -> str:
        """Generate Redis connection URL."""
        password = self.redis_password.get_secret_value()
        auth = f":{password}@" if password else ""
        return RedisDsn(
            f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"
        )

    # =============================================================================
    # Kafka Configuration
    # =============================================================================
    kafka_bootstrap_servers: str = Field(
        default="localhost:9092", description="Kafka bootstrap servers"
    )
    kafka_client_id: str = Field(default="sentinelai", description="Kafka client ID")
    kafka_consumer_group: str = Field(
        default="sentinelai-consumers", description="Kafka consumer group"
    )
    kafka_security_protocol: Literal[
        "PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"
    ] = Field(default="PLAINTEXT", description="Kafka security protocol")
    kafka_sasl_mechanism: Literal[
        "PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"
    ] = Field(default="PLAIN", description="SASL mechanism")
    kafka_sasl_username: str = Field(default="", description="SASL username")
    kafka_sasl_password: SecretStr = Field(default="", description="SASL password")
    kafka_auto_offset_reset: Literal["earliest", "latest", "none"] = Field(
        default="latest", description="Auto offset reset"
    )
    kafka_enable_auto_commit: bool = Field(
        default=True, description="Enable auto commit"
    )
    kafka_max_poll_records: int = Field(
        default=500, description="Max poll records"
    )

    # =============================================================================
    # ClickHouse Configuration
    # =============================================================================
    clickhouse_host: str = Field(default="localhost", description="ClickHouse host")
    clickhouse_port: int = Field(default=9000, description="ClickHouse port")
    clickhouse_database: str = Field(
        default="sentinelai", description="ClickHouse database"
    )
    clickhouse_user: str = Field(default="default", description="ClickHouse user")
    clickhouse_password: SecretStr = Field(default="", description="ClickHouse password")
    clickhouse_compression: Literal["lz4", "zstd", "none"] = Field(
        default="lz4", description="Compression algorithm"
    )

    @property
    def clickhouse_url(self) -> str:
        """Generate ClickHouse connection URL."""
        password = self.clickhouse_password.get_secret_value()
        auth = f"{self.clickhouse_user}:{password}@" if password else f"{self.clickhouse_user}@"
        return f"clickhouse://{auth}{self.clickhouse_host}:{self.clickhouse_port}/{self.clickhouse_database}"

    # =============================================================================
    # Qdrant (Vector Database) Configuration
    # =============================================================================
    qdrant_host: str = Field(default="localhost", description="Qdrant host")
    qdrant_port: int = Field(default=6333, description="Qdrant REST port")
    qdrant_grpc_port: int = Field(default=6334, description="Qdrant gRPC port")
    qdrant_api_key: SecretStr = Field(default="", description="Qdrant API key")
    qdrant_collection_name: str = Field(
        default="sentinelai_vectors", description="Vector collection name"
    )
    qdrant_distance: Literal["cosine", "euclidean", "dot"] = Field(
        default="cosine", description="Distance metric"
    )

    # =============================================================================
    # vLLM Configuration
    # =============================================================================
    vllm_host: str = Field(default="localhost", description="vLLM host")
    vllm_port: int = Field(default=8000, description="vLLM port")
    vllm_api_key: SecretStr = Field(default="EMPTY", description="vLLM API key")
    vllm_model: str = Field(
        default="llama-3-8b-instruct", description="vLLM model name"
    )
    vllm_max_tokens: int = Field(default=4096, description="Max tokens to generate")
    vllm_temperature: float = Field(default=0.7, description="Sampling temperature")
    vllm_top_p: float = Field(default=0.9, description="Top-p sampling")
    vllm_top_k: int = Field(default=50, description="Top-k sampling")

    @property
    def vllm_base_url(self) -> str:
        """Generate vLLM base URL."""
        return f"http://{self.vllm_host}:{self.vllm_port}/v1"

    # =============================================================================
    # Security Configuration
    # =============================================================================
    secret_key: SecretStr = Field(
        default="changeme-secret-key", description="Application secret key"
    )
    jwt_secret_key: SecretStr = Field(
        default="changeme-jwt-secret", description="JWT secret key"
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = Field(
        default="HS256", description="JWT algorithm"
    )
    jwt_access_token_expire_minutes: int = Field(
        default=30, description="Access token expiry in minutes"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7, description="Refresh token expiry in days"
    )
    jwt_reset_password_expire_minutes: int = Field(
        default=15, description="Password reset token expiry in minutes"
    )
    jwt_verification_expire_hours: int = Field(
        default=24, description="Email verification token expiry in hours"
    )

    # =============================================================================
    # CORS Configuration
    # =============================================================================
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8000"],
        description="Allowed CORS origins",
    )
    cors_allow_credentials: bool = Field(
        default=True, description="Allow credentials in CORS"
    )
    cors_allow_methods: list[str] = Field(
        default=["*"], description="Allowed HTTP methods"
    )
    cors_allow_headers: list[str] = Field(
        default=["*"], description="Allowed HTTP headers"
    )

    # =============================================================================
    # Rate Limiting Configuration
    # =============================================================================
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_requests: int = Field(
        default=100, description="Max requests per window"
    )
    rate_limit_window: int = Field(
        default=60, description="Rate limit window in seconds"
    )

    # =============================================================================
    # Logging Configuration
    # =============================================================================
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Log level"
    )
    log_format: Literal["json", "text"] = Field(
        default="json", description="Log format"
    )
    log_output: Literal["stdout", "file"] = Field(
        default="stdout", description="Log output"
    )
    log_include_timestamp: bool = Field(
        default=True, description="Include timestamp in logs"
    )
    log_include_correlation_id: bool = Field(
        default=True, description="Include correlation ID in logs"
    )
    log_include_request_id: bool = Field(
        default=True, description="Include request ID in logs"
    )

    # =============================================================================
    # OpenTelemetry Configuration
    # =============================================================================
    otel_enabled: bool = Field(default=True, description="Enable OpenTelemetry")
    otel_exporter_otlp_endpoint: str = Field(
        default="http://localhost:4317", description="OTLP exporter endpoint"
    )
    otel_exporter_otlp_insecure: bool = Field(
        default=True, description="Use insecure OTLP connection"
    )
    otel_service_name: str = Field(
        default="sentinelai", description="OTEL service name"
    )
    otel_resource_attributes: str = Field(
        default="service.name=sentinelai", description="OTEL resource attributes"
    )

    # =============================================================================
    # Prometheus Configuration
    # =============================================================================
    prometheus_enabled: bool = Field(
        default=True, description="Enable Prometheus metrics"
    )
    prometheus_port: int = Field(default=9090, description="Prometheus port")
    prometheus_namespace: str = Field(
        default="sentinelai", description="Prometheus metrics namespace"
    )

    # =============================================================================
    # Celery Configuration
    # =============================================================================
    celery_broker_url: str = Field(
        default="redis://localhost:6379/1", description="Celery broker URL"
    )
    celery_result_backend: str = Field(
        default="redis://localhost:6379/2", description="Celery result backend"
    )
    celery_task_serializer: Literal["json", "pickle", "msgpack"] = Field(
        default="json", description="Task serialization format"
    )
    celery_result_serializer: Literal["json", "pickle", "msgpack"] = Field(
        default="json", description="Result serialization format"
    )
    celery_accept_content: list[str] = Field(
        default=["json"], description="Accepted content types"
    )
    celery_timezone: str = Field(default="UTC", description="Celery timezone")
    celery_enable_utc: bool = Field(default=True, description="Enable UTC")
    celery_task_track_started: bool = Field(
        default=True, description="Track task start time"
    )
    celery_task_time_limit: int = Field(
        default=3600, description="Task time limit in seconds"
    )
    celery_worker_prefetch_multiplier: int = Field(
        default=4, description="Worker prefetch multiplier"
    )

    # =============================================================================
    # Temporal Configuration
    # =============================================================================
    temporal_address: str = Field(
        default="localhost:7233", description="Temporal server address"
    )
    temporal_namespace: str = Field(
        default="sentinelai", description="Temporal namespace"
    )
    temporal_task_queue: str = Field(
        default="sentinelai-task-queue", description="Temporal task queue"
    )
    temporal_connect_timeout: int = Field(
        default=10, description="Temporal connect timeout"
    )
    temporal_execution_timeout: int = Field(
        default=300, description="Temporal execution timeout"
    )

    # =============================================================================
    # AI Configuration
    # =============================================================================
    ai_provider: Literal["vllm", "openai", "anthropic", "azure"] = Field(
        default="vllm", description="AI provider"
    )
    ai_model: str = Field(default="llama-3-8b-instruct", description="AI model")
    ai_max_retries: int = Field(default=3, description="Max AI retries")
    ai_retry_delay: float = Field(default=1.0, description="AI retry delay")
    ai_timeout: int = Field(default=30, description="AI timeout in seconds")
    ai_temperature: float = Field(default=0.7, description="AI temperature")
    ai_top_p: float = Field(default=0.9, description="AI top-p")
    ai_top_k: int = Field(default=50, description="AI top-k")
    ai_max_tokens: int = Field(default=4096, description="AI max tokens")

    # Embedding Configuration
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Embedding model",
    )
    embedding_dimension: int = Field(
        default=384, description="Embedding dimension"
    )
    embedding_batch_size: int = Field(
        default=32, description="Embedding batch size"
    )

    # RAG Configuration
    rag_top_k: int = Field(default=10, description="RAG top-k results")
    rag_rerank_top_k: int = Field(
        default=5, description="RAG rerank top-k"
    )
    rag_similarity_threshold: float = Field(
        default=0.7, description="RAG similarity threshold"
    )
    rag_max_context_tokens: int = Field(
        default=8000, description="Max context tokens for RAG"
    )

    # =============================================================================
    # ML Configuration
    # =============================================================================
    ml_anomaly_detection_enabled: bool = Field(
        default=True, description="Enable anomaly detection"
    )
    ml_anomaly_threshold: float = Field(
        default=0.95, description="Anomaly detection threshold"
    )
    ml_forecasting_horizon: int = Field(
        default=24, description="Forecasting horizon in hours"
    )
    ml_change_point_threshold: float = Field(
        default=0.8, description="Change point detection threshold"
    )

    # =============================================================================
    # Notification Configuration
    # =============================================================================
    notification_email_enabled: bool = Field(
        default=False, description="Enable email notifications"
    )
    notification_email_host: str = Field(
        default="smtp.gmail.com", description="SMTP host"
    )
    notification_email_port: int = Field(
        default=587, description="SMTP port"
    )
    notification_email_username: str = Field(
        default="", description="SMTP username"
    )
    notification_email_password: SecretStr = Field(
        default="", description="SMTP password"
    )
    notification_email_from: EmailStr = Field(
        default="noreply@sentinelai.io", description="Email from address"
    )
    notification_email_use_tls: bool = Field(
        default=True, description="Use TLS for email"
    )

    notification_slack_enabled: bool = Field(
        default=False, description="Enable Slack notifications"
    )
    notification_slack_webhook_url: str = Field(
        default="", description="Slack webhook URL"
    )
    notification_slack_channel: str = Field(
        default="#incidents", description="Slack channel"
    )

    notification_pagerduty_enabled: bool = Field(
        default=False, description="Enable PagerDuty notifications"
    )
    notification_pagerduty_api_key: SecretStr = Field(
        default="", description="PagerDuty API key"
    )
    notification_pagerduty_service_id: str = Field(
        default="", description="PagerDuty service ID"
    )

    notification_discord_enabled: bool = Field(
        default=False, description="Enable Discord notifications"
    )
    notification_discord_webhook_url: str = Field(
        default="", description="Discord webhook URL"
    )

    # =============================================================================
    # Feature Flags
    # =============================================================================
    feature_anomaly_detection: bool = Field(
        default=True, description="Enable anomaly detection feature"
    )
    feature_auto_remediation: bool = Field(
        default=False, description="Enable auto-remediation feature"
    )
    feature_ai_suggestions: bool = Field(
        default=True, description="Enable AI suggestions feature"
    )
    feature_alert_deduplication: bool = Field(
        default=True, description="Enable alert deduplication feature"
    )
    feature_incident_timeline: bool = Field(
        default=True, description="Enable incident timeline feature"
    )
    feature_deployment_correlation: bool = Field(
        default=True, description="Enable deployment correlation feature"
    )
    feature_log_intelligence: bool = Field(
        default=True, description="Enable log intelligence feature"
    )
    feature_trace_analysis: bool = Field(
        default=True, description="Enable trace analysis feature"
    )

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        """Validate application environment."""
        if v not in ["development", "staging", "production"]:
            raise ValueError("app_env must be development, staging, or production")
        return v

    @model_validator(mode="after")
    def validate_production_settings(self) -> Settings:
        """Validate settings for production environment."""
        if self.app_env == "production":
            if self.app_debug:
                raise ValueError("Debug mode must be disabled in production")
            if self.secret_key.get_secret_value() == "changeme-secret-key":
                raise ValueError("Secret key must be changed in production")
            if self.jwt_secret_key.get_secret_value() == "changeme-jwt-secret":
                raise ValueError("JWT secret key must be changed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    This function caches the settings to avoid repeated validation
    and environment variable parsing.

    Returns:
        Settings: Application settings instance
    """
    return Settings()


# Create global settings instance
settings = get_settings()
