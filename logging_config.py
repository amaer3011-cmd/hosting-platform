"""
Structured logging configuration for production.
Supports both JSON (production) and console (development) formats.
"""

from __future__ import annotations

import logging
import logging.config
import sys
from pathlib import Path
from typing import Any

import structlog


def setup_logging(
    log_level: str = "INFO",
    log_format: str = "json",  # "json" or "console"
    log_file: str | Path | None = None,
    sentry_dsn: str | None = None,
) -> None:
    """
    Configure structured logging with structlog.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Output format - "json" for production, "console" for development
        log_file: Optional file path for log output
        sentry_dsn: Optional Sentry DSN for error tracking
    """
    
    # Configure standard library logging
    log_level_int = getattr(logging, log_level.upper(), logging.INFO)
    
    # Processors for structlog
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    
    if log_format == "json":
        # JSON format for production - machine parsable
        formatter_processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer()
        ]
        formatter_class = "logging.Formatter"
        formatter_fmt = "%(message)s"
    else:
        # Console format for development - human readable
        formatter_processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True)
        ]
        formatter_class = "logging.Formatter"
        formatter_fmt = "%(message)s"
    
    # Build logging config dict
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structured": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processors": formatter_processors,
                "foreign_pre_chain": shared_processors,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "structured",
                "stream": sys.stdout,
            },
        },
        "root": {
            "level": log_level_int,
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "uvicorn.error": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "uvicorn.access": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "sqlalchemy.engine": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "sqlalchemy.pool": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "aiogram": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "telegram": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "httpx": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "httpcore": {"level": "WARNING", "handlers": ["console"], "propagate": False},
            "celery": {"level": "INFO", "handlers": ["console"], "propagate": False},
            "redis": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        }
    }
    
    # Add file handler if log_file specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        config["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "structured",
            "filename": str(log_path),
            "maxBytes": 10_000_000,  # 10MB
            "backupCount": 5,
            "encoding": "utf-8",
        }
        config["root"]["handlers"].append("file")
        for logger_config in config["loggers"].values():
            logger_config["handlers"].append("file")
    
    # Apply configuration
    logging.config.dictConfig(config)
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Initialize Sentry if DSN provided
    if sentry_dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.logging import LoggingIntegration
            from sentry_sdk.integrations.asyncio import AsyncioIntegration
            from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
            from sentry_sdk.integrations.redis import RedisIntegration
            
            sentry_logging = LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR
            )
            
            sentry_sdk.init(
                dsn=sentry_dsn,
                integrations=[
                    sentry_logging,
                    AsyncioIntegration(),
                    SqlalchemyIntegration(),
                    RedisIntegration(),
                ],
                traces_sample_rate=0.1,
                profiles_sample_rate=0.1,
                environment="production",
            )
            logging.getLogger(__name__).info("Sentry initialized")
        except ImportError:
            logging.getLogger(__name__).warning("sentry-sdk not installed, skipping Sentry initialization")
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to initialize Sentry: {e}")


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


# Context managers for adding context to logs
class LogContext:
    """Context manager for adding structured context to logs."""
    
    def __init__(self, **kwargs):
        self.context = kwargs
        self.token = None
    
    def __enter__(self):
        self.token = structlog.contextvars.bind_contextvars(**self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            structlog.contextvars.unbind_contextvars(*self.context.keys())


# Convenience function for common logging patterns
def log_bot_event(logger: structlog.stdlib.BoundLogger, event: str, bot_id: int, **kwargs):
    """Log a bot-related event with standard context."""
    logger.info(event, bot_id=bot_id, **kwargs)


def log_user_event(logger: structlog.stdlib.BoundLogger, event: str, user_id: int, **kwargs):
    """Log a user-related event with standard context."""
    logger.info(event, user_id=user_id, **kwargs)


def log_admin_event(logger: structlog.stdlib.BoundLogger, event: str, admin_id: int, **kwargs):
    """Log an admin action with standard context."""
    logger.info(event, admin_id=admin_id, **kwargs)


def log_error_with_context(logger: structlog.stdlib.BoundLogger, error: Exception, **context):
    """Log an exception with structured context."""
    logger.error(
        "exception_occurred",
        error_type=type(error).__name__,
        error_message=str(error),
        **context,
        exc_info=True
    )