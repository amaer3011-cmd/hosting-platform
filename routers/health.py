"""
Health check and metrics endpoints.
"""

from __future__ import annotations

import time
from typing import Dict, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from database import get_async_db, global_stats as db_global_stats
from models import Bot, User, BotProcessState
from logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


# Track application start time
STARTED_AT = time.time()


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """Basic health check endpoint."""
    return {
        "status": "ok",
        "service": "telegram-bot-hosting",
        "version": "2.0.0",
        "uptime_seconds": round(time.time() - STARTED_AT, 2),
    }


@router.get("/healthz")
async def health_check_k8s() -> Dict[str, str]:
    """Kubernetes-style health check."""
    return {"status": "ok"}


@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_async_db)) -> Dict[str, Any]:
    """Readiness check - verifies database connectivity."""
    try:
        # Simple query to check DB connection
        await db.execute(select(1))
        db_status = "connected"
    except Exception as e:
        logger.error("readiness_check_db_failed", error=str(e))
        db_status = "disconnected"

    return {
        "status": "ready" if db_status == "connected" else "not_ready",
        "database": db_status,
        "uptime_seconds": round(time.time() - STARTED_AT, 2),
    }


@router.get("/metrics")
async def metrics(db: AsyncSession = Depends(get_async_db)) -> str:
    """Prometheus-compatible metrics endpoint."""
    stats = await db_global_stats()

    # Get running bots with process state
    result = await db.execute(
        select(BotProcessState).where(BotProcessState.status == "running")
    )
    running_states = result.scalars().all()

    total_cpu = 0.0
    total_mem_mb = 0.0
    running_bots = 0

    for state in running_states:
        if state.cpu_percent:
            try:
                total_cpu += float(state.cpu_percent.replace("%", ""))
            except (ValueError, AttributeError):
                pass
        if state.memory_mb:
            try:
                total_mem_mb += float(state.memory_mb)
            except (ValueError, TypeError):
                pass
        running_bots += 1

    lines = [
        "# HELP hosting_total_users Total registered users",
        "# TYPE hosting_total_users gauge",
        f"hosting_total_users {stats['total_users']}",
        "",
        "# HELP hosting_total_bots Total bots",
        "# TYPE hosting_total_bots gauge",
        f"hosting_total_bots {stats['total_bots']}",
        "",
        "# HELP hosting_running_bots Currently running bots",
        "# TYPE hosting_running_bots gauge",
        f"hosting_running_bots {stats['running']}",
        "",
        "# HELP hosting_crashed_bots Crashed bots",
        "# TYPE hosting_crashed_bots gauge",
        f"hosting_crashed_bots {stats['crashed']}",
        "",
        "# HELP hosting_total_cpu_percent Total CPU usage across all bots",
        "# TYPE hosting_total_cpu_percent gauge",
        f"hosting_total_cpu_percent {total_cpu:.2f}",
        "",
        "# HELP hosting_total_memory_mb Total memory usage across all bots (MB)",
        "# TYPE hosting_total_memory_mb gauge",
        f"hosting_total_memory_mb {total_mem_mb:.2f}",
        "",
        "# HELP hosting_uptime_seconds Service uptime in seconds",
        "# TYPE hosting_uptime_seconds gauge",
        f"hosting_uptime_seconds {round(time.time() - STARTED_AT, 2)}",
        "",
        "# HELP hosting_rate_limit_enabled Whether rate limiting is active",
        "# TYPE hosting_rate_limit_enabled gauge",
        f"hosting_rate_limit_enabled {1 if config.RATE_LIMIT_REQUESTS_PER_MINUTE > 0 else 0}",
        "",
        "# HELP hosting_rate_limit_per_minute Max requests per minute",
        "# TYPE hosting_rate_limit_per_minute gauge",
        f"hosting_rate_limit_per_minute {config.RATE_LIMIT_REQUESTS_PER_MINUTE}",
    ]

    return "\n".join(lines)


@router.get("/version")
async def version_info() -> Dict[str, Any]:
    """Version information."""
    return {
        "version": "2.0.0",
        "build_time": "2025-01-01T00:00:00Z",  # Would be injected at build time
        "git_commit": "unknown",  # Would be injected at build time
        "python_version": "3.11",
    }