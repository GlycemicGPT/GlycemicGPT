"""Story 1.5: Structured Logging Configuration.

Provides JSON-formatted logging with correlation IDs for request tracing.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

# Context variable for correlation ID - available throughout request lifecycle
correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


class JsonFormatter(logging.Formatter):
    """Custom formatter that outputs logs as JSON.

    Format includes:
    - timestamp: ISO 8601 format with timezone
    - level: Log level (INFO, ERROR, etc.)
    - service: Service name (glycemicgpt-api)
    - message: Log message
    - correlation_id: Request correlation ID for tracing
    - logger: Logger name
    - Additional fields from extra parameter
    """

    def __init__(self, service_name: str = "glycemicgpt-api"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON."""
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add correlation ID if available
        correlation_id = correlation_id_ctx.get()
        if correlation_id:
            log_data["correlation_id"] = correlation_id

        # Add extra fields if provided
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add location info for errors
        if record.levelno >= logging.ERROR:
            log_data["location"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        return json.dumps(log_data, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter for development.

    Format: timestamp - service - level - correlation_id - message
    """

    def __init__(self, service_name: str = "glycemicgpt-api"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as readable text."""
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        correlation_id = correlation_id_ctx.get() or "-"

        base_msg = (
            f"{timestamp} - {self.service_name} - {record.levelname} - "
            f"[{correlation_id}] - {record.getMessage()}"
        )

        # Add exception info if present
        if record.exc_info:
            base_msg += f"\n{self.formatException(record.exc_info)}"

        return base_msg


def setup_logging(
    log_format: str = "json",
    log_level: str = "INFO",
    service_name: str = "glycemicgpt-api",
) -> None:
    """Configure structured logging for the application.

    Args:
        log_format: 'json' for structured logging, 'text' for human-readable
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        service_name: Service name to include in logs
    """
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Select formatter based on format type
    if log_format.lower() == "json":
        formatter = JsonFormatter(service_name=service_name)
    else:
        formatter = TextFormatter(service_name=service_name)

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


class StructuredLogger:
    """Logger wrapper that supports structured extra fields."""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(self, level: int, msg: str, extra_fields: dict[str, Any] | None = None):
        """Log with optional extra fields."""
        exc_info = None
        if extra_fields:
            # Extract exc_info so it's forwarded to the underlying logger,
            # not buried inside extra_fields where it would be silently lost.
            extra_fields = dict(extra_fields)  # shallow copy to avoid mutating caller
            exc_info = extra_fields.pop("exc_info", None)
        record_extra = {"extra_fields": extra_fields} if extra_fields else {}
        self._logger.log(level, msg, exc_info=exc_info, extra=record_extra)

    def debug(self, msg: str, **extra_fields: Any) -> None:
        """Log debug message with optional extra fields."""
        self._log(logging.DEBUG, msg, extra_fields if extra_fields else None)

    def info(self, msg: str, **extra_fields: Any) -> None:
        """Log info message with optional extra fields."""
        self._log(logging.INFO, msg, extra_fields if extra_fields else None)

    def warning(self, msg: str, **extra_fields: Any) -> None:
        """Log warning message with optional extra fields."""
        self._log(logging.WARNING, msg, extra_fields if extra_fields else None)

    def error(self, msg: str, **extra_fields: Any) -> None:
        """Log error message with optional extra fields."""
        self._log(logging.ERROR, msg, extra_fields if extra_fields else None)

    def exception(self, msg: str, **extra_fields: Any) -> None:
        """Log exception with traceback and optional extra fields."""
        record_extra = {"extra_fields": extra_fields} if extra_fields else {}
        self._logger.exception(msg, extra=record_extra)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        StructuredLogger instance
    """
    return StructuredLogger(name)
