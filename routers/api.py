"""
API endpoints for bot management.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import config
from database import (
    get_async_db,
    get_user,
    get_or_create_user,
    get_user_bots,
    count_user_bots,
    get_bot,
    get_bot_full,
    insert_bot,
    insert_bot_if_room,
    update_bot,
    delete_bot,
    set_bot_files,
    set_bot_status,
    set_env_var,
    get_env_vars,
    list_env_vars,
    delete_env_var,
    set_max_memory,
    set_restart_interval,
    set_auto_restart,
    toggle_auto_restart,
    get_all_bots,
    global_stats,
    save_process_state,
    get_process_state,
    create_deployment,
    update_deployment,
    get_deployments,
    create_backup_record,
    update_backup_record,
    get_backup_records,
)
from models import Bot, User
from middleware.rate_limit import rate_limit_api, rate_limit_admin
from logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


# --- Pydantic models ---

class BotCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    max_memory_mb: Optional[int] = Field(None, ge=128, le=2048)


class BotUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    max_memory_mb: Optional[int] = Field(None, ge=128, le=2048)
    restart_interval_hours: Optional[int] = Field(None, ge=0)
    auto_restart: Optional[bool] = None


class EnvVarCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=255, pattern=r'^[A-Za-z][A-Za-z0-9_]*$')
    value: str = Field(..., min_length=1)


class EnvVarResponse(BaseModel):
    key: str
    display_value: str


class BotResponse(BaseModel):
    bot_id: int
    owner_id: int
    name: str
    folder: Optional[str]
    entry_file: Optional[str]
    status: str
    max_memory_mb: Optional[int]
    restart_interval_hours: int
    auto_restart: bool
    last_started_at: Optional[str]
    last_stopped_at: Optional[str]
    crash_count: int
    last_error: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class BotDetailResponse(BotResponse):
    env_vars: List[EnvVarResponse] = []


class BotProcessStateResponse(BaseModel):
    bot_id: int
    container_id: Optional[str]
    pid: Optional[int]
    status: str
    started_at: Optional[str]
    last_heartbeat: Optional[str]
    restart_count: int
    cpu_percent: Optional[str]
    memory_percent: Optional[str]
    memory_mb: Optional[int]
    exit_code: Optional[int]
    error_message: Optional[str]


class DeploymentCreate(BaseModel):
    version: Optional[str] = None


class DeploymentResponse(BaseModel):
    id: int
    bot_id: int
    version: Optional[str]
    status: str
    image_tag: Optional[str]
    build_logs: Optional[str]
    deployed_by: Optional[int]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: Optional[str]

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    total_users: int
    total_bots: int
    running: int
    crashed: int


class ProcessStateUpdate(BaseModel):
    container_id: Optional[str] = None
    pid: Optional[int] = None
    status: Optional[str] = None
    cpu_percent: Optional[str] = None
    memory_percent: Optional[str] = None
    memory_mb: Optional[int] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None


# --- Dependency for authenticated user ---
async def get_current_user(
    user_id: int = Query(..., description="Telegram user ID"),
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """Get current user from query param (in production, use JWT/auth)."""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="User is banned")
    return user


# --- Bot endpoints ---

@router.get("/bots", response_model=List[BotResponse])
@rate_limit_api("60/minute")
async def list_bots(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[BotResponse]:
    """List all bots for the current user."""
    bots = await get_user_bots(user.id)
    return [BotResponse.model_validate(bot) for bot in bots]


@router.post("/bots", response_model=BotResponse, status_code=201)
@rate_limit_api("30/minute")
async def create_bot(
    bot_data: BotCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BotResponse:
    """Create a new bot."""
    bot_id = await insert_bot_if_room(
        owner_id=user.id,
        name=bot_data.name,
        max_bots=user.max_bots,
        max_memory_mb=bot_data.max_memory_mb,
    )
    if bot_id is None:
        raise HTTPException(status_code=400, detail="Bot limit reached")

    bot = await get_bot(bot_id)
    logger.info("bot_created", bot_id=bot_id, owner_id=user.id, name=bot_data.name)
    return BotResponse.model_validate(bot)


@router.get("/bots/{bot_id}", response_model=BotDetailResponse)
@rate_limit_api("60/minute")
async def get_bot_detail(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BotDetailResponse:
    """Get bot details including environment variables."""
    bot = await get_bot_full(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Check ownership
    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    env_vars = await list_env_vars(bot_id)
    response = BotDetailResponse.model_validate(bot)
    response.env_vars = [EnvVarResponse(**ev) for ev in env_vars]
    return response


@router.patch("/bots/{bot_id}", response_model=BotResponse)
@rate_limit_api("30/minute")
async def update_bot_settings(
    bot_id: int,
    bot_data: BotUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BotResponse:
    """Update bot settings."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_data = bot_data.model_dump(exclude_unset=True)
    updated_bot = await update_bot(bot_id, **update_data)
    logger.info("bot_updated", bot_id=bot_id, owner_id=user.id, fields=list(update_data.keys()))
    return BotResponse.model_validate(updated_bot)


@router.delete("/bots/{bot_id}", status_code=204)
@rate_limit_api("10/minute")
async def delete_bot_endpoint(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Delete a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    await delete_bot(bot_id)
    logger.info("bot_deleted", bot_id=bot_id, owner_id=user.id)


# --- Bot control endpoints ---

@router.post("/bots/{bot_id}/start")
@rate_limit_api("20/minute")
async def start_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Start a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if bot.status == "running":
        return {"ok": True, "message": "Bot is already running"}

    # Import process manager
    from process_manager import manager
    ok, message = manager().start_bot(bot)

    if ok:
        await set_bot_status(bot_id, "running")
        await save_process_state(bot_id, {"status": "starting"})
        logger.info("bot_started", bot_id=bot_id, owner_id=user.id)
        return {"ok": True, "message": message}
    else:
        await set_bot_status(bot_id, "crashed", error=message)
        logger.warning("bot_start_failed", bot_id=bot_id, error=message)
        raise HTTPException(status_code=500, detail=message)


@router.post("/bots/{bot_id}/stop")
@rate_limit_api("20/minute")
async def stop_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Stop a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if bot.status == "stopped":
        return {"ok": True, "message": "Bot is already stopped"}

    from process_manager import manager
    ok, message = manager().stop_bot(bot_id)

    if ok:
        await set_bot_status(bot_id, "stopped")
        await save_process_state(bot_id, {"status": "stopped"})
        logger.info("bot_stopped", bot_id=bot_id, owner_id=user.id)
        return {"ok": True, "message": message}
    else:
        logger.warning("bot_stop_failed", bot_id=bot_id, error=message)
        raise HTTPException(status_code=500, detail=message)


@router.post("/bots/{bot_id}/restart")
@rate_limit_api("20/minute")
async def restart_bot(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Restart a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from process_manager import manager
    ok, message = manager().restart_bot(bot)

    if ok:
        await set_bot_status(bot_id, "running")
        await save_process_state(bot_id, {"status": "restarting", "restart_count": 1})
        logger.info("bot_restarted", bot_id=bot_id, owner_id=user.id)
        return {"ok": True, "message": message}
    else:
        await set_bot_status(bot_id, "crashed", error=message)
        logger.warning("bot_restart_failed", bot_id=bot_id, error=message)
        raise HTTPException(status_code=500, detail=message)


@router.get("/bots/{bot_id}/logs")
@rate_limit_api("30/minute")
async def get_bot_logs(
    bot_id: int,
    lines: int = Query(100, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Get bot logs."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if not bot.folder:
        return {"logs": "No folder configured"}

    from pathlib import Path
    log_path = Path(bot.folder) / "run.log"
    if not log_path.exists():
        return {"logs": "Log file not found"}

    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        log_lines = content.splitlines()[-lines:]
        return {"logs": "\n".join(log_lines)}
    except Exception as e:
        logger.error("logs_read_failed", bot_id=bot_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to read logs")


@router.get("/bots/{bot_id}/usage")
@rate_limit_api("30/minute")
async def get_bot_usage(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Get bot resource usage."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    from process_manager import manager
    usage = manager().get_usage(bot_id)
    if not usage:
        return {"cpu": "0%", "mem": "0 MB", "uptime": "0s"}

    return usage


@router.get("/bots/{bot_id}/health", response_model=BotProcessStateResponse)
@rate_limit_api("30/minute")
async def get_bot_health(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> BotProcessStateResponse:
    """Get detailed health status for a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    process_state = await get_process_state(bot_id)
    if not process_state:
        # Return default/unknown state
        return BotProcessStateResponse(
            bot_id=bot_id,
            container_id=None,
            pid=None,
            status=bot.status,
            started_at=None,
            last_heartbeat=None,
            restart_count=0,
            cpu_percent=None,
            memory_percent=None,
            memory_mb=None,
            exit_code=None,
            error_message=None,
        )

    return BotProcessStateResponse.model_validate(process_state)


# --- Environment variable endpoints ---

@router.get("/bots/{bot_id}/env", response_model=List[EnvVarResponse])
@rate_limit_api("30/minute")
async def list_bot_env_vars(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[EnvVarResponse]:
    """List environment variables for a bot (masked values)."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    env_vars = await list_env_vars(bot_id)
    return [EnvVarResponse(**ev) for ev in env_vars]


@router.post("/bots/{bot_id}/env", response_model=EnvVarResponse, status_code=201)
@rate_limit_api("20/minute")
async def create_env_var(
    bot_id: int,
    env_data: EnvVarCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> EnvVarResponse:
    """Set an environment variable for a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Check protected keys
    if env_data.key.upper() in config.PROTECTED_ENV_KEYS:
        raise HTTPException(status_code=400, detail="This environment variable is protected")

    await set_env_var(bot_id, env_data.key.upper(), env_data.value)
    logger.info("env_var_created", bot_id=bot_id, key=env_data.key.upper(), owner_id=user.id)

    return EnvVarResponse(key=env_data.key.upper(), display_value="***MASKED***")


@router.delete("/bots/{bot_id}/env/{key}", status_code=204)
@rate_limit_api("20/minute")
async def delete_env_var_endpoint(
    bot_id: int,
    key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Delete an environment variable."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if key.upper() in config.PROTECTED_ENV_KEYS:
        raise HTTPException(status_code=400, detail="This environment variable is protected")

    await delete_env_var(bot_id, key.upper())
    logger.info("env_var_deleted", bot_id=bot_id, key=key.upper(), owner_id=user.id)


# --- Bot settings endpoints ---

@router.patch("/bots/{bot_id}/memory")
@rate_limit_api("20/minute")
async def update_bot_memory(
    bot_id: int,
    memory_mb: Optional[int] = Body(None, embed=True, ge=128, le=2048),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Update bot memory limit."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    await set_max_memory(bot_id, memory_mb)
    logger.info("bot_memory_updated", bot_id=bot_id, memory_mb=memory_mb, owner_id=user.id)
    return {"ok": True, "memory_mb": memory_mb}


@router.patch("/bots/{bot_id}/restart-schedule")
@rate_limit_api("20/minute")
async def update_restart_schedule(
    bot_id: int,
    hours: int = Body(..., embed=True, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Update bot restart schedule."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    if hours not in config.RESTART_INTERVAL_CHOICES_HOURS:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Choose from: {config.RESTART_INTERVAL_CHOICES_HOURS}")

    await set_restart_interval(bot_id, hours)
    logger.info("bot_restart_schedule_updated", bot_id=bot_id, hours=hours, owner_id=user.id)
    return {"ok": True, "hours": hours}


@router.post("/bots/{bot_id}/auto-restart")
@rate_limit_api("20/minute")
async def toggle_auto_restart_endpoint(
    bot_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Toggle auto restart for a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    enabled = await toggle_auto_restart(bot_id)
    logger.info("bot_auto_restart_toggled", bot_id=bot_id, enabled=enabled, owner_id=user.id)
    return {"ok": True, "auto_restart": enabled}


# --- Deployment endpoints ---

@router.post("/bots/{bot_id}/deploy", response_model=DeploymentResponse, status_code=201)
@rate_limit_api("10/minute")
async def create_deployment_endpoint(
    bot_id: int,
    deployment_data: DeploymentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> DeploymentResponse:
    """Create a new deployment for a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    deployment = await create_deployment(bot_id, deployment_data.version, user.id)
    logger.info("deployment_created", bot_id=bot_id, deployment_id=deployment.id, owner_id=user.id)
    return DeploymentResponse.model_validate(deployment)


@router.get("/bots/{bot_id}/deployments", response_model=List[DeploymentResponse])
@rate_limit_api("30/minute")
async def list_deployments(
    bot_id: int,
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[DeploymentResponse]:
    """List deployments for a bot."""
    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    deployments = await get_deployments(bot_id, limit)
    return [DeploymentResponse.model_validate(d) for d in deployments]


# --- Admin endpoints ---

@router.get("/admin/stats", response_model=StatsResponse)
@rate_limit_admin("60/minute")
async def admin_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> StatsResponse:
    """Get platform statistics (admin only)."""
    # In production, check admin role
    stats = await global_stats()
    return StatsResponse(**stats)


@router.get("/admin/bots", response_model=List[BotResponse])
@rate_limit_admin("60/minute")
async def admin_list_bots(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> List[BotResponse]:
    """List all bots (admin)."""
    bots = await get_all_bots()
    if status:
        bots = [b for b in bots if b.status == status]
    bots = bots[offset:offset + limit]
    return [BotResponse.model_validate(bot) for bot in bots]


@router.get("/admin/backups")
@rate_limit_admin("30/minute")
async def admin_list_backups(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    limit: int = Query(50, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """List backup records (admin)."""
    backups = await get_backup_records(limit)
    return [b.to_dict() for b in backups]


# --- Process state update (for workers) ---

@router.post("/internal/bots/{bot_id}/process-state")
async def update_process_state(
    bot_id: int,
    state: ProcessStateUpdate,
    api_key: str = Header(..., alias="X-Internal-API-Key"),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Internal endpoint for workers to update bot process state."""
    # Verify internal API key
    if api_key != config.INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid internal API key")

    bot = await get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    state_dict = state.model_dump(exclude_unset=True)
    await save_process_state(bot_id, state_dict)

    # Also update bot status if provided
    if state.status:
        await set_bot_status(bot_id, state.status, state.error_message)

    return {"ok": True}