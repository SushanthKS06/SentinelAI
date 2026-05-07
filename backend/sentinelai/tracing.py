"""SentinelAI Observability Module.

Provides OpenTelemetry integration for distributed tracing,
metrics collection, and automatic instrumentation.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Callable, Generator, TypeVar

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.trace import (
    Span,
    SpanKind,
    Status,
    StatusCode,
    Tracer,
    get_tracer,
    get_tracer_provider,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from sentinelai.config import settings
from sentinelai.logging import get_logger

logger = get_logger(__name__)

# Type variable for generic decorators
F = TypeVar("F", bound=Callable[..., Any])

# Global tracer instance
_tracer: Tracer | None = None
_propagator = TraceContextTextMapPropagator()


def init_tracing(service_name: str | None = None) -> Tracer:
    """Initialize OpenTelemetry tracing.

    Args:
        service_name: Service name for tracing (defaults to settings)

    Returns:
        Configured tracer instance
    """
    global _tracer

    if not settings.otel_enabled:
        logger.warning("OpenTelemetry is disabled")
        return get_tracer(__name__)

    # Create resource with service metadata
    resource = Resource.create(
        {
            SERVICE_NAME: service_name or settings.otel_service_name,
            SERVICE_VERSION: settings.app_version,
            "deployment.environment": settings.app_env,
        }
    )

    # Setup tracer provider
    provider = TracerProvider(resource=resource)

    # Add OTLP exporter if configured
    if settings.otel_exporter_otlp_endpoint:
        try:
            otlp_exporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                insecure=settings.otel_exporter_otlp_insecure,
            )
            provider.add_span_processor(BatchSpanExporter(otlp_exporter))
            logger.info(f"OTLP exporter configured: {settings.otel_exporter_otlp_endpoint}")
        except Exception as e:
            logger.warning(f"Failed to configure OTLP exporter: {e}")

    # Add console exporter for development
    if settings.app_env == "development":
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = get_tracer(service_name or settings.otel_service_name)

    # Instrument logging
    try:
        LoggingInstrumentor().instrument(set_logging_format=True)
    except Exception as e:
        logger.warning(f"Failed to instrument logging: {e}")

    logger.info(f"Tracing initialized for service: {service_name or settings.otel_service_name}")
    return _tracer


class BatchSpanExporter(SpanProcessor):
    """Custom batch span processor with error handling."""

    def __init__(self, exporter: Any):
        self.exporter = exporter
        self._batch = []

    def on_end(self, span: Span) -> None:
        """Handle span end."""
        try:
            self.exporter.export([span]) if hasattr(self.exporter, 'export') else None
        except Exception as e:
            logger.error(f"Failed to export span: {e}")

    def on_start(self, span: Span) -> None:
        """Handle span start."""
        pass

    def shutdown(self) -> None:
        """Shutdown the processor."""
        pass


def get_tracer(name: str | None = None) -> Tracer:
    """Get a tracer instance.

    Args:
        name: Tracer name (defaults to service name)

    Returns:
        Tracer instance
    """
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(
            name or settings.otel_service_name,
            settings.app_version,
        )
    return _tracer


def instrument_fastapi(app: Any) -> None:
    """Instrument FastAPI application.

    Args:
        app: FastAPI application instance
    """
    if not settings.otel_enabled:
        return

    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")
    except Exception as e:
        logger.warning(f"Failed to instrument FastAPI: {e}")


# Context managers for tracing
class tracer:
    """Context manager for creating spans.

    Usage:
        with tracer("operation_name") as span:
            span.set_attribute("key", "value")
            # do work
    """

    def __init__(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ):
        self.name = name
        self.kind = kind
        self.attributes = attributes or {}
        self._span: Span | None = None

    def __enter__(self) -> Span:
        t = get_tracer()
        self._span = t.start_span(
            self.name,
            kind=self.kind,
            attributes=self.attributes,
        )
        return self._span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._span:
            if exc_type:
                self._span.set_status(Status(StatusCode.ERROR, str(exc_val)))
                self._span.record_exception(exc_val)
            self._span.end()


class async_tracer:
    """Async context manager for creating spans."""

    def __init__(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: dict[str, Any] | None = None,
    ):
        self.name = name
        self.kind = kind
        self.attributes = attributes or {}
        self._span: Span | None = None

    async def __aenter__(self) -> Span:
        t = get_tracer()
        self._span = t.start_span(
            self.name,
            kind=self.kind,
            attributes=self.attributes,
        )
        return self._span

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._span:
            if exc_type:
                self._span.set_status(Status(StatusCode.ERROR, str(exc_val)))
                self._span.record_exception(exc_val)
            self._span.end()


# Decorators for automatic tracing
def traced(
    name: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    """Decorator to automatically trace function execution.

    Args:
        name: Span name (defaults to function name)
        kind: Span kind
        attributes: Initial attributes

    Returns:
        Decorated function
    """
    def decorator(func: F) -> F:
        span_name = name or func.__name__

        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with async_tracer(span_name, kind, attributes) as span:
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)
                return await func(*args, **kwargs)

        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer(span_name, kind, attributes) as span:
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)
                return func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper  # type: ignore

    return decorator


# Trace context propagation
def inject_trace_context(carrier: dict[str, str]) -> None:
    """Inject trace context into carrier for propagation.

    Args:
        carrier: Dictionary to inject context into
    """
    _propagator.inject(carrier)


def extract_trace_context(carrier: dict[str, str]) -> dict[str, Any]:
    """Extract trace context from carrier.

    Args:
        carrier: Dictionary containing trace context

    Returns:
        Extracted context as span context
    """
    return _propagator.extract(carrier)


# Export commonly used items
__all__ = [
    "init_tracing",
    "get_tracer",
    "instrument_fastapi",
    "tracer",
    "async_tracer",
    "traced",
    "inject_trace_context",
    "extract_trace_context",
    "SpanKind",
    "StatusCode",
    "Span",
    "Tracer",
]
