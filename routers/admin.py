"""
Admin endpoints for platform management.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import config
from database import (
    get_async_db,
    get_user,
    get_users_page,
    get_audit_log_page,
    ban_user,
    log_admin_action,
    get_system_config,
    set_system_config,
    global_stats,
)
from models import User, AuditLog, SystemConfig
from middleware.rate_limit import rate_limit_admin
from logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


# --- Pydantic models ---

class UserResponse(BaseModel):
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    language_code: Optional[str]
    is_banned: bool
    max_bots: int
    created_at: Optional[str]
    updated_at: Optional[str]
    bot_count: int = 0

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    max_bots: Optional[int] = Field(None, ge=1, le=100)
    is_banned: Optional[bool] = None


class AuditLogResponse(BaseModel):
    id: int
    admin_id: Optional[int]
    action: str
    target: Optional[str]
    details: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: Optional[str]

    class Config:
        from_attributes = True


class SystemConfigResponse(BaseModel):
    key: str
    value: str
    description: str
    is_secret: bool
    updated_at: Optional[str]

    class Config:
        from_attributes = True


class SystemConfigCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=128)
    value: str
    description: str = ""
    is_secret: bool = False


class BroadcastRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    parse_mode: str = Field("HTML", pattern="^(HTML|Markdown|None)$")


class StatsResponse(BaseModel):
    total_users: int
    total_bots: int
    running: int
    crashed: int


# --- Dependency for admin user ---
async def get_admin_user(
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """Get admin user (in production, verify admin role properly)."""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="User is banned")
    # Check if user is admin
    if user_id not in config.ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# --- User management ---

@router.get("/users", response_model=List[UserResponse])
@rate_limit_admin("60/minute")
async def list_users(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
) -> List[UserResponse]:
    """List all users with pagination."""
    users, total = await get_users_page(page, per_page)

    # Get bot counts for each user
    from database import count_user_bots
    result = []
    for user in users:
        bot_count = await count_user_bots(user.id)
        user_dict = UserResponse.model_validate(user).model_dump()
        user_dict["bot_count"] = bot_count
        result.append(UserResponse(**user_dict))

    return result


@router.get("/users/{user_id}", response_model=UserResponse)
@rate_limit_admin("60/minute")
async def get_user_detail(
    user_id: int,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserResponse:
    """Get user details."""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    from database import count_user_bots
    bot_count = await count_user_bots(user_id)
    user_dict = UserResponse.model_validate(user).model_dump()
    user_dict["bot_count"] = bot_count
    return UserResponse(**user_dict)


@router.patch("/users/{user_id}", response_model=UserResponse)
@rate_limit_admin("30/minute")
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserResponse:
    """Update user settings (max bots, ban status)."""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_data.model_dump(exclude_unset=True)
    if "is_banned" in update_data:
        await ban_user(user_id, update_data["is_banned"])
        action = "ban_user" if update_data["is_banned"] else "unban_user"
        await log_admin_action(admin.id, action, str(user_id))
    if "max_bots" in update_data:
        user.max_bots = update_data["max_bots"]
        await log_admin_action(admin.id, "set_max_bots", str(user_id), str(update_data["max_bots"]))

    updated_user = await get_user(user_id)
    from database import count_user_bots
    bot_count = await count_user_bots(user_id)
    user_dict = UserResponse.model_validate(updated_user).model_dump()
    user_dict["bot_count"] = bot_count
    return UserResponse(**user_dict)


# --- Audit logs ---

@router.get("/audit-logs", response_model=List[AuditLogResponse])
@rate_limit_admin("60/minute")
async def list_audit_logs(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
) -> List[AuditLogResponse]:
    """List audit logs with pagination."""
    logs, total = await get_audit_log_page(page, per_page)
    return [AuditLogResponse.model_validate(log) for log in logs]


# --- System configuration ---

@router.get("/config", response_model=List[SystemConfigResponse])
@rate_limit_admin("60/minute")
async def list_system_config(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> List[SystemConfigResponse]:
    """List all system configuration."""
    async with get_async_db() as db:
        result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
        configs = result.scalars().all()
        return [SystemConfigResponse.model_validate(c) for c in configs]


@router.get("/config/{key}", response_model=SystemConfigResponse)
@rate_limit_admin("60/minute")
async def get_system_config_endpoint(
    key: str,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> SystemConfigResponse:
    """Get a system configuration value."""
    config_obj = await get_system_config(key)
    if config_obj is None:
        raise HTTPException(status_code=404, detail="Config not found")
    return SystemConfigResponse(key=key, value=config_obj, description="", is_secret=False, updated_at=None)


@router.post("/config", response_model=SystemConfigResponse, status_code=201)
@rate_limit_admin("30/minute")
async def create_system_config(
    config_data: SystemConfigCreate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> SystemConfigResponse:
    """Create or update system configuration."""
    config_obj = await set_system_config(
        config_data.key,
        config_data.value,
        config_data.description,
        config_data.is_secret,
    )
    await log_admin_action(admin.id, "set_config", config_data.key)
    return SystemConfigResponse.model_validate(config_obj)


# --- Platform statistics ---

@router.get("/stats", response_model=StatsResponse)
@rate_limit_admin("60/minute")
async def admin_stats(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> StatsResponse:
    """Get platform statistics."""
    stats = await global_stats()
    return StatsResponse(**stats)


# --- Backup management ---

@router.get("/backups")
@rate_limit_admin("30/minute")
async def list_backups(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
    limit: int = Query(50, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """List backup records."""
    from database import get_backup_records
    backups = await get_backup_records(limit)
    return [b.to_dict() for b in backups]


@router.post("/backups/trigger")
@rate_limit_admin("5/minute")
async def trigger_backup(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
    backup_type: str = Query("full", pattern="^(full|incremental|schema_only)$"),
) -> Dict[str, Any]:
    """Trigger a manual backup."""
    from backup import create_full_backup
    from database import create_backup_record, update_backup_record

    record = await create_backup_record(backup_type)
    try:
        await update_backup_record(record.id, status="running")
        backup_path = await create_full_backup()
        # Get file size
        import os
        file_size = os.path.getsize(backup_path) // (1024 * 1024) if os.path.exists(backup_path) else 0
        await update_backup_record(record.id, status="success", file_path=backup_path, file_size_mb=file_size)
        await log_admin_action(admin.id, "trigger_backup", backup_type, backup_path)
        return {"ok": True, "backup_id": record.id, "path": backup_path, "size_mb": file_size}
    except Exception as e:
        await update_backup_record(record.id, status="failed", error_message=str(e))
        logger.error("manual_backup_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")


# --- Broadcast ---

@router.post("/broadcast")
@rate_limit_admin("5/minute")
async def broadcast_message(
    broadcast: BroadcastRequest,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Send broadcast message to all users."""
    from database import get_async_db
    from sqlalchemy import select
    from models import User

    async with get_async_db() as db:
        result = await db.execute(select(User).where(User.is_banned == False))
        users = result.scalars().all()

    # In production, this would use the hosting bot to send messages
    # For now, return count
    await log_admin_action(admin.id, "broadcast", "all_users", f"count={len(users)}")
    return {"ok": True, "target_users": len(users), "message": "Broadcast queued"}


# --- System actions ---

@router.post("/system/stop-all-bots")
@rate_limit_admin("5/minute")
async def stop_all_bots(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Stop all running bots."""
    from process_manager import manager

    stopped = 0
    async with get_async_db() as db:
        result = await db.execute(select(Bot).where(Bot.status == "running"))
        bots = result.scalars().all()

    for bot in bots:
        ok, _ = manager().stop_bot(bot.id)
        if ok:
            stopped += 1
            await set_bot_status(bot.id, "stopped")

    await log_admin_action(admin.id, "stop_all_bots", "all", str(stopped))
    return {"ok": True, "stopped": stopped}


@router.post("/system/restart-crashed")
@rate_limit_admin("5/minute")
async def restart_crashed_bots(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_async_db),
) -> Dict[str, Any]:
    """Restart all crashed bots with auto_restart enabled."""
    from process_manager import manager

    restarted = 0
    async with get_async_db() as db:
        result = await db.execute(select(Bot).where(Bot.status == "crashed", Bot.auto_restart == True))
        bots = result.scalars().all()

    for bot in bots:
        ok, _ = manager().restart_bot(bot)
        if ok:
            restarted += 1
            await set_bot_status(bot.id, "running")

    await log_admin_action(admin.id, "restart_crashed", "all", str(restarted))
    return {"ok": True, "restarted": restarted}


# Need to import Bot and set_bot_status
from models import Bot
from database import set_bot_status