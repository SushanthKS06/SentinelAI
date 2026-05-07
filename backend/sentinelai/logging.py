"""SentinelAI Logging Module.

Provides structured logging with correlation IDs, JSON formatting,
and integration with OpenTelemetry for distributed tracing.
"""

from __future__ import annotations

import logging
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable
from functools import wraps

from sentinelai.config import settings

# Context variables for correlation
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)


def generate_correlation_id() -> str:
    """Generate a unique correlation ID."""
    import uuid
    return f"corr-{uuid.uuid4().hex[:16]}"


def generate_request_id() -> str:
    """Generate a unique request ID."""
    import uuid
    return f"req-{uuid.uuid4().hex[:16]}"


class JSONFormatter(logging.Formatter):
    """JSON log formatter with structured output."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        import orjson

        # Build base log structure
        log_data: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add correlation IDs if available
        corr_id = _correlation_id.get()
        req_id = _request_id.get()
        usr_id = _user_id.get()
        tnt_id = _tenant_id.get()

        if corr_id:
            log_data["correlation_id"] = corr_id
        if req_id:
            log_data["request_id"] = req_id
        if usr_id:
            log_data["user_id"] = usr_id
        if tnt_id:
            log_data["tenant_id"] = tnt_id

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info),
            }

        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
            ):
                if not key.startswith("_"):
                    log_data[key] = value

        return orjson.dumps(log_data, default=str).decode("utf-8")


class PlainFormatter(logging.Formatter):
    """Plain text formatter for development."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as plain text."""
        corr_id = _correlation_id.get()
        corr_str = f" [{corr_id}]" if corr_id else ""
        return (
            f"{self.formatTime(record, self.datefmt)} {record.levelname:8} "
            f"{record.name}{corr_str}: {record.getMessage()}"
        )


def setup_logging(
    name: str | None = None,
    level: str | None = None,
    json_format: bool | None = None,
) -> logging.Logger:
    """Setup and configure logging for a service.

    Args:
        name: Logger name (defaults to service name from settings)
        level: Log level override
        json_format: Use JSON format override

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name or settings.otel_service_name)

    # Determine log level
    log_level = getattr(
        logging, (level or settings.log_level).upper(), logging.INFO
    )
    logger.setLevel(log_level)

    # Clear existing handlers
    logger.handlers.clear()

    # Determine format
    use_json = json_format if json_format is not None else (settings.log_format == "json")
    formatter = JSONFormatter() if use_json else PlainFormatter()

    # Add console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(log_level)
    logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Context managers for correlation
class CorrelationContext:
    """Context manager for setting correlation IDs."""

    def __init__(
        self,
        correlation_id: str | None = None,
        request_id: str | None = None,
        user_id: str | None = None,
        tenant_id: str | None = None,
    ):
        self.correlation_id = correlation_id or generate_correlation_id()
        self.request_id = request_id or generate_request_id()
        self.user_id = user_id
        self.tenant_id = tenant_id
        self._token: tuple | None = None

    def __enter__(self) -> "CorrelationContext":
        self._token = (
            _correlation_id.set(self.correlation_id),
            _request_id.set(self.request_id),
            _user_id.set(self.user_id),
            _tenant_id.set(self.tenant_id),
        )
        return self

    def __exit__(self, *args: Any) -> None:
        if self._token:
            _correlation_id.reset(self._token[0])
            _request_id.reset(self._token[1])
            _user_id.reset(self._token[2])
            _tenant_id.reset(self._token[3])


def log_execution_time(logger: logging.Logger | None = None):
    """Decorator to log function execution time.

    Args:
        logger: Logger instance (defaults to module logger)
    """
    def decorator(func: Callable) -> Callable:
        nonlocal logger
        if logger is None:
            logger = get_logger(func.__module__)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.perf_counter() - start
                logger.info(
                    f"Function {func.__name__} executed in {duration:.4f}s",
                    extra={"duration_ms": duration * 1000},
                )

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.perf_counter() - start
                logger.info(
                    f"Function {func.__name__} executed in {duration:.4f}s",
                    extra={"duration_ms": duration * 1000},
                )

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# Export commonly used items
__all__ = [
    "get_logger",
    "setup_logging",
    "CorrelationContext",
    "generate_correlation_id",
    "generate_request_id",
    "log_execution_time",
    "_correlation_id",
    "_request_id",
    "_user_id",
    "_tenant_id",
]
