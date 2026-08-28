"""
Bot process health checker - runs inside bot containers to report health.
"""

from __future__ import annotations

import os
import time
import asyncio
import aiohttp
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

@dataclass
class HealthStatus:
    """Health status of a bot process."""
    status: str  # healthy, unhealthy, starting, stopping
    uptime_seconds: float
    cpu_percent: float
    memory_mb: int
    memory_percent: float
    last_update: float
    checks: Dict[str, bool]


class BotHealthChecker:
    """
    Health checker that runs inside bot containers.
    Reports health to the hosting platform via HTTP.
    """

    def __init__(
        self,
        bot_id: int,
        platform_url: str,
        internal_api_key: str,
        check_interval: int = 30,
    ):
        self.bot_id = bot_id
        self.platform_url = platform_url.rstrip("/")
        self.internal_api_key = internal_api_key
        self.check_interval = check_interval
        self.start_time = time.time()
        self.last_checks: Dict[str, bool] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the health checker."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        # Send initial health
        await self._report_health("starting")

    async def stop(self) -> None:
        """Stop the health checker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._report_health("stopping")

    async def _run_loop(self) -> None:
        """Main health check loop."""
        while self._running:
            try:
                health = await self._check_health()
                await self._report_health("healthy" if health.checks.get("process", False) else "unhealthy", health)
            except Exception as e:
                print(f"Health check failed: {e}")
            await asyncio.sleep(self.check_interval)

    async def _check_health(self) -> HealthStatus:
        """Perform health checks."""
        import psutil

        process = psutil.Process(os.getpid())
        uptime = time.time() - self.start_time

        # CPU and memory
        cpu_percent = process.cpu_percent(interval=0.1)
        memory_info = process.memory_info()
        memory_mb = memory_info.rss // (1024 * 1024)
        memory_percent = process.memory_percent()

        # Custom checks
        checks = {
            "process": True,  # Process is alive
            "memory": memory_percent < 90,  # Memory under 90%
            "cpu": cpu_percent < 95,  # CPU under 95%
        }

        # Check for bot-specific health (e.g., Telegram connection)
        checks["telegram"] = await self._check_telegram_connection()

        overall_healthy = all(checks.values())

        return HealthStatus(
            status="healthy" if overall_healthy else "unhealthy",
            uptime_seconds=uptime,
            cpu_percent=cpu_percent,
            memory_mb=memory_mb,
            memory_percent=memory_percent,
            last_update=time.time(),
            checks=checks,
        )

    async def _check_telegram_connection(self) -> bool:
        """Check if bot can connect to Telegram API."""
        # This would be implemented by the bot itself
        # For now, return True
        return True

    async def _report_health(self, status: str, health: Optional[HealthStatus] = None) -> None:
        """Report health to platform."""
        if health is None:
            health = await self._check_health()

        payload = {
            "bot_id": self.bot_id,
            "status": status,
            "cpu_percent": f"{health.cpu_percent:.1f}%",
            "memory_percent": f"{health.memory_percent:.1f}%",
            "memory_mb": health.memory_mb,
            "uptime": f"{health.uptime_seconds:.0f}s",
        }

        headers = {
            "X-Internal-API-Key": self.internal_api_key,
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.platform_url}/api/internal/bots/{self.bot_id}/process-state",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        print(f"Health report failed: {resp.status}")
        except Exception as e:
            print(f"Health report error: {e}")


# --- FastAPI endpoint for bot to expose its own health ---

from fastapi import APIRouter, Response
from pydantic import BaseModel

health_router = APIRouter()


class BotHealthResponse(BaseModel):
    status: str
    uptime_seconds: float
    cpu_percent: float
    memory_mb: int
    memory_percent: float
    checks: Dict[str, bool]


@health_router.get("/health", response_model=BotHealthResponse)
async def bot_health():
    """Health endpoint for the bot itself."""
    import psutil
    import os

    process = psutil.Process(os.getpid())
    uptime = time.time() - float(os.environ.get("BOT_START_TIME", time.time()))

    cpu_percent = process.cpu_percent(interval=0.1)
    memory_info = process.memory_info()
    memory_mb = memory_info.rss // (1024 * 1024)
    memory_percent = process.memory_percent()

    checks = {
        "process": True,
        "memory": memory_percent < 90,
        "cpu": cpu_percent < 95,
    }

    return BotHealthResponse(
        status="healthy" if all(checks.values()) else "unhealthy",
        uptime_seconds=uptime,
        cpu_percent=cpu_percent,
        memory_mb=memory_mb,
        memory_percent=memory_percent,
        checks=checks,
    )


@health_router.get("/healthz")
async def bot_healthz():
    """Kubernetes-style health check."""
    return {"status": "ok"}


# --- Helper to integrate into user bots ---

def create_health_check_app(bot_id: int, platform_url: str, internal_api_key: str) -> tuple:
    """
    Create health checker and router for integration into user bots.
    
    Usage in user bot:
        from health_checker import create_health_check_app, health_router
        checker, router = create_health_check_app(bot_id, platform_url, api_key)
        app.include_router(router)
        await checker.start()
    """
    checker = BotHealthChecker(bot_id, platform_url, internal_api_key)
    return checker, health_router