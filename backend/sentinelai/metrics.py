"""SentinelAI Metrics Module.

Provides Prometheus metrics collection with custom metrics
for AI inference, queue monitoring, and service health.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Generator

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Info,
    Summary,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from prometheus_client.core import (
    CollectorRegistry,
    REGISTRY,
    CounterMetricFamily,
    GaugeMetricFamily,
    HistogramMetricFamily,
)
from prometheus_client.multiprocessing import MultiProcessCollector

from sentinelai.config import settings
from sentinelai.logging import get_logger

logger = get_logger(__name__)

# Global registry
_registry: CollectorRegistry | None = None


def get_registry() -> CollectorRegistry:
    """Get or create metrics registry."""
    global _registry
    if _registry is None:
        if settings.app_env == "production":
            _registry = CollectorRegistry()
            MultiProcessCollector(_registry)
        else:
            _registry = REGISTRY
    return _registry


# =============================================================================
# Custom Metrics
# =============================================================================


class SentinelAIMetrics:
    """Custom metrics for SentinelAI platform."""

    def __init__(self, namespace: str = "sentinelai"):
        self.namespace = namespace
        ns = lambda name: f"{namespace}_{name}"

        # Request metrics
        self.requests_total = Counter(
            ns("requests_total"),
            "Total number of requests",
            ["method", "endpoint", "status"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.request_duration = Histogram(
            ns("request_duration_seconds"),
            "Request duration in seconds",
            ["method", "endpoint"],
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            namespace=namespace,
            registry=get_registry(),
        )

        # Active connections
        self.active_connections = Gauge(
            ns("active_connections"),
            "Number of active connections",
            ["service"],
            namespace=namespace,
            registry=get_registry(),
        )

        # Queue metrics
        self.queue_size = Gauge(
            ns("queue_size"),
            "Current queue size",
            ["queue", "topic"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.queue_messages_processed = Counter(
            ns("queue_messages_processed_total"),
            "Total messages processed",
            ["queue", "topic", "status"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.queue_processing_duration = Histogram(
            ns("queue_processing_duration_seconds"),
            "Message processing duration",
            ["queue", "topic"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            namespace=namespace,
            registry=get_registry(),
        )

        # AI/ML metrics
        self.ai_requests_total = Counter(
            ns("ai_requests_total"),
            "Total AI requests",
            ["model", "provider", "status"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.ai_tokens_total = Counter(
            ns("ai_tokens_total"),
            "Total tokens processed",
            ["model", "type"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.ai_request_duration = Histogram(
            ns("ai_request_duration_seconds"),
            "AI request duration",
            ["model", "operation"],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 60.0],
            namespace=namespace,
            registry=get_registry(),
        )

        self.ai_model_loaded = Gauge(
            ns("ai_model_loaded"),
            "Whether AI model is loaded",
            ["model"],
            namespace=namespace,
            registry=get_registry(),
        )

        # Database metrics
        self.db_connections_active = Gauge(
            ns("db_connections_active"),
            "Active database connections",
            ["database"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.db_query_duration = Histogram(
            ns("db_query_duration_seconds"),
            "Database query duration",
            ["operation", "table"],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            namespace=namespace,
            registry=get_registry(),
        )

        # Cache metrics
        self.cache_hits = Counter(
            ns("cache_hits_total"),
            "Total cache hits",
            ["cache"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.cache_misses = Counter(
            ns("cache_misses_total"),
            "Total cache misses",
            ["cache"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.cache_size = Gauge(
            ns("cache_size"),
            "Current cache size",
            ["cache"],
            namespace=namespace,
            registry=get_registry(),
        )

        # Incident metrics
        self.incidents_total = Counter(
            ns("incidents_total"),
            "Total incidents",
            ["severity", "status", "source"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.incident_duration = Histogram(
            ns("incident_duration_minutes"),
            "Incident duration in minutes",
            ["severity"],
            buckets=[1, 5, 15, 30, 60, 120, 360, 720, 1440],
            namespace=namespace,
            registry=get_registry(),
        )

        # Alert metrics
        self.alerts_firing = Gauge(
            ns("alerts_firing"),
            "Number of firing alerts",
            ["severity", "service"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.alerts_total = Counter(
            ns("alerts_total"),
            "Total alerts",
            ["severity", "status"],
            namespace=namespace,
            registry=get_registry(),
        )

        # Anomaly detection metrics
        self.anomalies_detected = Counter(
            ns("anomalies_detected_total"),
            "Total anomalies detected",
            ["type", "service", "severity"],
            namespace=namespace,
            registry=get_registry(),
        )

        self.anomaly_score = Histogram(
            ns("anomaly_score"),
            "Anomaly detection score",
            ["type", "service"],
            buckets=[0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0],
            namespace=namespace,
            registry=get_registry(),
        )

        # RAG/Retrieval metrics
        self.rag_retrieval_duration = Histogram(
            ns("rag_retrieval_duration_seconds"),
            "RAG retrieval duration",
            ["stage"],
            buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
            namespace=namespace,
            registry=get_registry(),
        )

        self.rag_chunks_retrieved = Histogram(
            ns("rag_chunks_retrieved"),
            "Number of chunks retrieved",
            buckets=[1, 3, 5, 10, 20, 50, 100],
            namespace=namespace,
            registry=get_registry(),
        )

        self.rag_similarity_score = Histogram(
            ns("rag_similarity_score"),
            "RAG similarity score",
            buckets=[0.0, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0],
            namespace=namespace,
            registry=get_registry(),
        )

        # Service info
        self.service_info = Info(
            ns("service"),
            "Service information",
            namespace=namespace,
            registry=get_registry(),
        )


# Global metrics instance
metrics = SentinelAIMetrics(settings.prometheus_namespace)


# =============================================================================
# Decorators and Context Managers
# =============================================================================


def track_request(method: str, endpoint: str):
    """Decorator to track request metrics.

    Args:
        method: HTTP method
        endpoint: API endpoint
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            status = "success"
            try:
                return await func(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start
                metrics.requests_total.labels(
                    method=method,
                    endpoint=endpoint,
                    status=status,
                ).inc()
                metrics.request_duration.labels(
                    method=method,
                    endpoint=endpoint,
                ).observe(duration)

        return wrapper
    return decorator


def track_ai_request(model: str, provider: str):
    """Decorator to track AI request metrics.

    Args:
        model: AI model name
        provider: AI provider
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            status = "success"
            try:
                return await func(*args, **kwargs)
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start
                metrics.ai_requests_total.labels(
                    model=model,
                    provider=provider,
                    status=status,
                ).inc()
                metrics.ai_request_duration.labels(
                    model=model,
                    operation=func.__name__,
                ).observe(duration)

        return wrapper
    return decorator


@contextmanager
def track_db_query(operation: str, table: str) -> Generator[None, None, None]:
    """Context manager to track database query metrics.

    Args:
        operation: Query operation (select, insert, update, delete)
        table: Table name
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        metrics.db_query_duration.labels(
            operation=operation,
            table=table,
        ).observe(duration)


@contextmanager
def track_queue_processing(queue: str, topic: str) -> Generator[None, None, None]:
    """Context manager to track queue processing metrics.

    Args:
        queue: Queue name
        topic: Kafka topic
    """
    start = time.perf_counter()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        duration = time.perf_counter() - start
        metrics.queue_messages_processed.labels(
            queue=queue,
            topic=topic,
            status=status,
        ).inc()
        metrics.queue_processing_duration.labels(
            queue=queue,
            topic=topic,
        ).observe(duration)


# =============================================================================
# Metrics Endpoint
# =============================================================================


def get_metrics() -> bytes:
    """Generate Prometheus metrics output.

    Returns:
        Prometheus metrics in text format
    """
    return generate_latest(get_registry())


def get_metrics_content_type() -> str:
    """Get Prometheus content type.

    Returns:
        Content type string
    """
    return CONTENT_TYPE_LATEST


# Export commonly used items
__all__ = [
    "get_registry",
    "get_metrics",
    "get_metrics_content_type",
    "metrics",
    "SentinelAIMetrics",
    "track_request",
    "track_ai_request",
    "track_db_query",
    "track_queue_processing",
]
