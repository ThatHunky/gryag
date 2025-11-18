"""Logging configuration with file rotation and cleanup."""

from __future__ import annotations

import json
import logging
import logging.handlers

from app.config import Settings


class JSONFormatter(logging.Formatter):
    """Format log records as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields by scanning record.__dict__ (logging injects extras as attributes)
        std_attrs = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
        }
        extras: dict[str, object] = {}

        def _mask(val: str) -> str:
            if not isinstance(val, str) or len(val) < 6:
                return "***"
            return val[:3] + "..." + val[-2:]

        for key, value in record.__dict__.items():
            if key in std_attrs:
                continue
            # Mask sensitive keys
            lk = key.lower()
            if any(
                s in lk for s in ("token", "api_key", "apikey", "secret", "password")
            ):
                try:
                    extras[key] = _mask(value)  # type: ignore[arg-type]
                except Exception:
                    extras[key] = "***"
                continue
            # Ensure JSON-safe (fallback to str for unsupported types)
            if isinstance(value, (str, int, float, bool)) or value is None:
                extras[key] = value
            else:
                try:
                    # Basic containers: make best effort shallow conversion
                    if isinstance(value, (list, tuple)):
                        extras[key] = [
                            (
                                v
                                if isinstance(v, (str, int, float, bool)) or v is None
                                else str(v)
                            )
                            for v in value
                        ]
                    elif isinstance(value, dict):
                        extras[key] = {
                            str(k): (
                                v
                                if isinstance(v, (str, int, float, bool)) or v is None
                                else str(v)
                            )
                            for k, v in value.items()
                        }
                    else:
                        extras[key] = str(value)
                except Exception:
                    extras[key] = str(value)

        if extras:
            log_data["extra"] = extras

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(settings: Settings) -> None:
    """
    Configure application logging with rotation and cleanup.

    Creates:
    - Console handler (optional)
    - File handler with daily rotation
    - Automatic cleanup of old logs
    """
    # Create logs directory
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))
    root_logger.handlers.clear()  # Remove any existing handlers

    # Formatter
    if settings.log_format == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Console handler
    if settings.enable_console_logging:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler with time-based rotation (daily at midnight)
    if settings.enable_file_logging:
        log_file = settings.log_dir / "gryag.log"

        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=settings.log_retention_days,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)

    logging.info(
        "Logging configured",
        extra={
            "log_dir": str(settings.log_dir),
            "log_level": settings.log_level,
            "log_format": settings.log_format,
            "console": settings.enable_console_logging,
            "file": settings.enable_file_logging,
            "retention_days": settings.log_retention_days,
        },
    )


def cleanup_old_logs(settings: Settings) -> None:
    """
    Manually remove logs older than retention period.

    TimedRotatingFileHandler handles this automatically,
    but this can be called for manual cleanup.
    """
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(days=settings.log_retention_days)
    cutoff_timestamp = cutoff.timestamp()

    deleted_count = 0
    for log_file in settings.log_dir.glob("gryag.log.*"):
        # Check modification time
        if log_file.stat().st_mtime < cutoff_timestamp:
            log_file.unlink()
            deleted_count += 1

    if deleted_count > 0:
        logging.info(f"Cleaned up {deleted_count} old log files")
