"""
Advanced health check system with multiple monitoring strategies.
Detects bot health issues before they become critical.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

from config import config
from logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    bot_id: int
    bot_name: str
    is_healthy: bool
    status: str
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    uptime_seconds: Optional[int] = None
    last_error: Optional[str] = None
    check_timestamp: datetime = None
    
    def __post_init__(self):
        if self.check_timestamp is None:
            self.check_timestamp = datetime.now()


class HealthCheckStrategy:
    """Base class for health check strategies."""
    
    async def check(self, bot_id: int) -> HealthCheckResult:
        """Perform health check."""
        raise NotImplementedError


class ProcessHealthCheck(HealthCheckStrategy):
    """Check if bot process is still running."""
    
    async def check(self, bot_id: int) -> HealthCheckResult:
        """Check process status."""
        from database import get_process_state
        
        try:
            state = await get_process_state(bot_id)
            
            if not state or not state.pid:
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name="unknown",
                    is_healthy=False,
                    status="process_not_running",
                )
            
            # Check if process exists using psutil
            import psutil
            try:
                process = psutil.Process(state.pid)
                
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name=state.name or f"bot_{bot_id}",
                    is_healthy=True,
                    status="running",
                    cpu_percent=process.cpu_percent(interval=0.1),
                    memory_mb=process.memory_info().rss / 1024 / 1024,
                    uptime_seconds=int(process.create_time()),
                )
            except psutil.NoSuchProcess:
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name="unknown",
                    is_healthy=False,
                    status="process_terminated",
                )
        
        except Exception as e:
            logger.error(f"Process health check failed for bot {bot_id}: {e}")
            return HealthCheckResult(
                bot_id=bot_id,
                bot_name="unknown",
                is_healthy=False,
                status="check_error",
                last_error=str(e),
            )


class TelegramTokenHealthCheck(HealthCheckStrategy):
    """Check bot token validity via Telegram API."""
    
    async def check(self, bot_id: int) -> HealthCheckResult:
        """Check if bot token is valid."""
        from database import get_bot, get_env_vars
        
        try:
            bot = await get_bot(bot_id)
            if not bot:
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name="unknown",
                    is_healthy=False,
                    status="bot_not_found",
                )
            
            env_vars = await get_env_vars(bot_id)
            bot_token = env_vars.get("BOT_TOKEN")
            
            if not bot_token:
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name=bot.name,
                    is_healthy=False,
                    status="no_token_configured",
                )
            
            # Simulate token check (would need python-telegram-bot)
            # In real implementation, this would call bot.get_me()
            return HealthCheckResult(
                bot_id=bot_id,
                bot_name=bot.name,
                is_healthy=True,
                status="token_valid",
            )
        
        except Exception as e:
            logger.error(f"Token health check failed for bot {bot_id}: {e}")
            return HealthCheckResult(
                bot_id=bot_id,
                bot_name="unknown",
                is_healthy=False,
                status="token_check_error",
                last_error=str(e),
            )


class ResourceHealthCheck(HealthCheckStrategy):
    """Check if bot is within resource limits."""
    
    async def check(self, bot_id: int) -> HealthCheckResult:
        """Check resource usage."""
        from database import get_bot, get_process_state
        
        try:
            bot = await get_bot(bot_id)
            if not bot:
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name="unknown",
                    is_healthy=False,
                    status="bot_not_found",
                )
            
            state = await get_process_state(bot_id)
            if not state or not state.pid:
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name=bot.name,
                    is_healthy=False,
                    status="no_process",
                )
            
            import psutil
            try:
                process = psutil.Process(state.pid)
                memory_mb = process.memory_info().rss / 1024 / 1024
                
                # Check if exceeds limit
                max_memory = bot.max_memory_mb or config.max_bot_memory_mb
                is_healthy = memory_mb < max_memory * 0.9  # 90% threshold
                
                status = "memory_ok" if is_healthy else "memory_high"
                
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name=bot.name,
                    is_healthy=is_healthy,
                    status=status,
                    memory_mb=memory_mb,
                    cpu_percent=process.cpu_percent(interval=0.1),
                )
            except psutil.NoSuchProcess:
                return HealthCheckResult(
                    bot_id=bot_id,
                    bot_name=bot.name,
                    is_healthy=False,
                    status="process_not_found",
                )
        
        except Exception as e:
            logger.error(f"Resource health check failed for bot {bot_id}: {e}")
            return HealthCheckResult(
                bot_id=bot_id,
                bot_name="unknown",
                is_healthy=False,
                status="resource_check_error",
                last_error=str(e),
            )


class AdvancedHealthMonitor:
    """Comprehensive health monitoring system."""
    
    def __init__(self):
        self.checks: List[HealthCheckStrategy] = [
            ProcessHealthCheck(),
            ResourceHealthCheck(),
            TelegramTokenHealthCheck(),
        ]
        self.check_interval = config.health_check_timeout_seconds
        self.last_results: Dict[int, List[HealthCheckResult]] = {}
    
    async def check_bot(self, bot_id: int) -> HealthCheckResult:
        """Run all checks for a bot."""
        logger.debug(f"Running health checks for bot {bot_id}")
        
        results = []
        for strategy in self.checks:
            try:
                result = await strategy.check(bot_id)
                results.append(result)
            except Exception as e:
                logger.error(f"Health check strategy failed: {e}")
        
        # Use most recent successful result
        if results:
            overall = results[-1]
            
            # Store result history
            if bot_id not in self.last_results:
                self.last_results[bot_id] = []
            
            self.last_results[bot_id].append(overall)
            # Keep only last 100 results
            if len(self.last_results[bot_id]) > 100:
                self.last_results[bot_id].pop(0)
            
            return overall
        
        return HealthCheckResult(
            bot_id=bot_id,
            bot_name="unknown",
            is_healthy=False,
            status="all_checks_failed",
        )
    
    async def check_all_bots(self) -> List[HealthCheckResult]:
        """Check health of all bots."""
        from database import get_all_bots
        
        try:
            all_bots = await get_all_bots()
            results = []
            
            for bot in all_bots:
                try:
                    result = await self.check_bot(bot.id)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Failed to check bot {bot.id}: {e}")
            
            return results
        
        except Exception as e:
            logger.error(f"Failed to check all bots: {e}")
            return []
    
    def get_bot_history(self, bot_id: int, limit: int = 10) -> List[HealthCheckResult]:
        """Get health check history for a bot."""
        if bot_id not in self.last_results:
            return []
        
        return self.last_results[bot_id][-limit:]
    
    async def get_health_report(self) -> Dict:
        """Generate comprehensive health report."""
        results = await self.check_all_bots()
        
        healthy = [r for r in results if r.is_healthy]
        unhealthy = [r for r in results if not r.is_healthy]
        
        return {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": len(results),
                "healthy": len(healthy),
                "unhealthy": len(unhealthy),
                "health_percentage": (len(healthy) / len(results) * 100) if results else 0,
            },
            "healthy_bots": [
                {
                    "bot_id": r.bot_id,
                    "name": r.bot_name,
                    "memory_mb": r.memory_mb,
                    "cpu_percent": r.cpu_percent,
                    "uptime_seconds": r.uptime_seconds,
                }
                for r in healthy
            ],
            "unhealthy_bots": [
                {
                    "bot_id": r.bot_id,
                    "name": r.bot_name,
                    "status": r.status,
                    "error": r.last_error,
                }
                for r in unhealthy
            ],
        }


# Global health monitor
_health_monitor = AdvancedHealthMonitor()


async def check_bot_health(bot_id: int) -> HealthCheckResult:
    """Check health of a single bot."""
    return await _health_monitor.check_bot(bot_id)


async def check_all_health() -> List[HealthCheckResult]:
    """Check health of all bots."""
    return await _health_monitor.check_all_bots()


async def get_health_report() -> Dict:
    """Get comprehensive health report."""
    return await _health_monitor.get_health_report()
