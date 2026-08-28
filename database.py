"""
Database operations layer - async CRUD for all models.
Provides high-level async interface for the application.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import select, func, delete, update, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import (
    Base,
    User,
    Bot,
    EnvVar,
    BotProcessState,
    Deployment,
    AuditLog,
    BackupRecord,
    SystemConfig,
    init_db,
    get_async_db,
    upsert_bot_process_state,
    get_bot_process_state,
    get_running_bots,
    update_bot_status,
    create_audit_log,
    get_bot_with_relations,
)

# Re-export for backward compatibility
__all__ = [
    "Base",
    "User",
    "Bot",
    "EnvVar",
    "BotProcessState",
    "Deployment",
    "AuditLog",
    "BackupRecord",
    "SystemConfig",
    "init_db",
    "get_async_db",
    # High-level operations
    "get_user",
    "get_or_create_user",
    "update_user",
    "ban_user",
    "get_user_bots",
    "count_user_bots",
    "get_bot",
    "get_bot_full",
    "insert_bot",
    "insert_bot_if_room",
    "update_bot",
    "delete_bot",
    "set_bot_files",
    "set_bot_status",
    "set_env_var",
    "get_env_vars",
    "list_env_vars",
    "delete_env_var",
    "set_max_memory",
    "set_restart_interval",
    "set_auto_restart",
    "toggle_auto_restart",
    "get_all_bots",
    "global_stats",
    "get_users_page",
    "get_audit_log_page",
    "log_admin_action",
    "get_system_config",
    "set_system_config",
    # Process state
    "save_process_state",
    "get_process_state",
    # Deployments
    "create_deployment",
    "update_deployment",
    "get_deployments",
    # Backups
    "create_backup_record",
    "update_backup_record",
    "get_backup_records",
]


# --- User operations ---

async def get_user(user_id: int) -> Optional[User]:
    """Get user by Telegram ID."""
    async with get_async_db() as db:
        return await db.get(User, user_id)


async def get_or_create_user(
    user_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    language_code: Optional[str] = None,
) -> User:
    """Get existing user or create new one."""
    async with get_async_db() as db:
        user = await db.get(User, user_id)
        if user:
            # Update profile info
            if username is not None:
                user.username = username
            if first_name is not None:
                user.first_name = first_name
            if last_name is not None:
                user.last_name = last_name
            if language_code is not None:
                user.language_code = language_code
            user.updated_at = datetime.utcnow()
        else:
            user = User(
                id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
            )
            db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def update_user(user_id: int, **kwargs) -> Optional[User]:
    """Update user fields."""
    async with get_async_db() as db:
        user = await db.get(User, user_id)
        if user:
            for key, value in kwargs.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            user.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(user)
        return user


async def ban_user(user_id: int, banned: bool = True) -> bool:
    """Ban or unban a user."""
    async with get_async_db() as db:
        user = await db.get(User, user_id)
        if user:
            user.is_banned = banned
            user.updated_at = datetime.utcnow()
            await db.commit()
            return True
        return False


# --- Bot operations ---

async def get_user_bots(user_id: int) -> List[Bot]:
    """Get all bots owned by a user."""
    async with get_async_db() as db:
        result = await db.execute(
            select(Bot)
            .where(Bot.owner_id == user_id)
            .order_by(Bot.created_at.desc())
        )
        return list(result.scalars().all())


async def count_user_bots(user_id: int) -> int:
    """Count bots owned by a user."""
    async with get_async_db() as db:
        result = await db.execute(
            select(func.count(Bot.id)).where(Bot.owner_id == user_id)
        )
        return result.scalar() or 0


async def get_bot(bot_id: int) -> Optional[Bot]:
    """Get bot by ID."""
    async with get_async_db() as db:
        return await db.get(Bot, bot_id)


async def get_bot_full(bot_id: int) -> Optional[Bot]:
    """Get bot with all relationships."""
    return await get_bot_with_relations(bot_id)


async def insert_bot(
    owner_id: int,
    name: str,
    folder: str = "",
    entry_file: str = "",
    max_memory_mb: Optional[int] = None,
) -> Bot:
    """Create a new bot."""
    async with get_async_db() as db:
        bot = Bot(
            owner_id=owner_id,
            name=name,
            folder=folder,
            entry_file=entry_file,
            max_memory_mb=max_memory_mb,
            status="stopped",
        )
        db.add(bot)
        await db.commit()
        await db.refresh(bot)
        return bot


async def insert_bot_if_room(
    owner_id: int,
    name: str,
    max_bots: int,
    max_memory_mb: Optional[int] = None,
) -> Optional[int]:
    """Create a new bot if user hasn't reached their limit. Returns bot_id or None."""
    count = await count_user_bots(owner_id)
    if count >= max_bots:
        return None

    bot = await insert_bot(owner_id, name, max_memory_mb=max_memory_mb)
    return bot.id


async def update_bot(bot_id: int, **kwargs) -> Optional[Bot]:
    """Update bot fields."""
    async with get_async_db() as db:
        bot = await db.get(Bot, bot_id)
        if bot:
            for key, value in kwargs.items():
                if hasattr(bot, key):
                    setattr(bot, key, value)
            bot.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(bot)
        return bot


async def delete_bot(bot_id: int) -> bool:
    """Delete a bot and all related data."""
    async with get_async_db() as db:
        bot = await db.get(Bot, bot_id)
        if bot:
            await db.delete(bot)
            await db.commit()
            return True
        return False


async def set_bot_files(bot_id: int, folder: str, entry_file: str) -> bool:
    """Update bot folder and entry file."""
    return await update_bot(bot_id, folder=folder, entry_file=entry_file) is not None


async def set_bot_status(bot_id: int, status: str, error: Optional[str] = None) -> None:
    """Update bot status."""
    await update_bot_status(bot_id, status, error)


# --- Environment variables ---

async def set_env_var(bot_id: int, key: str, value: str) -> EnvVar:
    """Set or update an environment variable for a bot (value will be encrypted)."""
    from env_crypto import env_crypto

    encrypted_value = env_crypto.encrypt_value(value)
    display_value = env_crypto.mask_value(value)

    async with get_async_db() as db:
        # Check if exists
        result = await db.execute(
            select(EnvVar).where(and_(EnvVar.bot_id == bot_id, EnvVar.key == key))
        )
        env_var = result.scalar_one_or_none()

        if env_var:
            env_var.value_encrypted = encrypted_value
            env_var.display_value = display_value
        else:
            env_var = EnvVar(
                bot_id=bot_id,
                key=key,
                value_encrypted=encrypted_value,
                display_value=display_value,
            )
            db.add(env_var)

        await db.commit()
        await db.refresh(env_var)
        return env_var


async def get_env_vars(bot_id: int) -> Dict[str, str]:
    """Get all environment variables for a bot (decrypted)."""
    from env_crypto import env_crypto

    async with get_async_db() as db:
        result = await db.execute(
            select(EnvVar).where(EnvVar.bot_id == bot_id)
        )
        env_vars = result.scalars().all()
        return {
            ev.key: env_crypto.decrypt_value(ev.value_encrypted)
            for ev in env_vars
        }


async def list_env_vars(bot_id: int) -> List[Dict[str, Any]]:
    """Get environment variables with masked display values."""
    async with get_async_db() as db:
        result = await db.execute(
            select(EnvVar).where(EnvVar.bot_id == bot_id)
        )
        env_vars = result.scalars().all()
        return [
            {
                "key": ev.key,
                "display_value": ev.display_value,
            }
            for ev in env_vars
        ]


async def delete_env_var(bot_id: int, key: str) -> bool:
    """Delete an environment variable."""
    async with get_async_db() as db:
        result = await db.execute(
            select(EnvVar).where(and_(EnvVar.bot_id == bot_id, EnvVar.key == key))
        )
        env_var = result.scalar_one_or_none()
        if env_var:
            await db.delete(env_var)
            await db.commit()
            return True
        return False


# --- Bot settings ---

async def set_max_memory(bot_id: int, memory_mb: Optional[int]) -> bool:
    """Set max memory for a bot."""
    bot = await update_bot(bot_id, max_memory_mb=memory_mb)
    return bot is not None


async def set_restart_interval(bot_id: int, hours: int) -> bool:
    """Set restart interval for a bot."""
    bot = await update_bot(bot_id, restart_interval_hours=hours)
    return bot is not None


async def set_auto_restart(bot_id: int, enabled: bool) -> bool:
    """Set auto restart for a bot."""
    bot = await update_bot(bot_id, auto_restart=enabled)
    return bot is not None


async def toggle_auto_restart(bot_id: int) -> bool:
    """Toggle auto restart for a bot."""
    async with get_async_db() as db:
        bot = await db.get(Bot, bot_id)
        if bot:
            bot.auto_restart = not bot.auto_restart
            bot.updated_at = datetime.utcnow()
            await db.commit()
            return bot.auto_restart
    return False


# --- Admin operations ---

async def get_all_bots() -> List[Bot]:
    """Get all bots (admin)."""
    async with get_async_db() as db:
        result = await db.execute(
            select(Bot).order_by(Bot.created_at.desc())
        )
        return list(result.scalars().all())


async def global_stats() -> Dict[str, int]:
    """Get global platform statistics."""
    async with get_async_db() as db:
        total_users = await db.execute(select(func.count(User.id)))
        total_bots = await db.execute(select(func.count(Bot.id)))
        running_bots = await db.execute(
            select(func.count(Bot.id)).where(Bot.status == "running")
        )
        crashed_bots = await db.execute(
            select(func.count(Bot.id)).where(Bot.status == "crashed")
        )

        return {
            "total_users": total_users.scalar() or 0,
            "total_bots": total_bots.scalar() or 0,
            "running": running_bots.scalar() or 0,
            "crashed": crashed_bots.scalar() or 0,
        }


async def get_users_page(page: int, per_page: int) -> Tuple[List[User], int]:
    """Get paginated users."""
    async with get_async_db() as db:
        total = await db.execute(select(func.count(User.id)))
        total_count = total.scalar() or 0

        offset = (page - 1) * per_page
        result = await db.execute(
            select(User)
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        users = list(result.scalars().all())
        return users, total_count


async def get_audit_log_page(page: int, per_page: int) -> Tuple[List[AuditLog], int]:
    """Get paginated audit logs."""
    async with get_async_db() as db:
        total = await db.execute(select(func.count(AuditLog.id)))
        total_count = total.scalar() or 0

        offset = (page - 1) * per_page
        result = await db.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(per_page)
        )
        logs = list(result.scalars().all())
        return logs, total_count


async def log_admin_action(
    admin_id: int,
    action: str,
    target: Optional[str] = None,
    details: Optional[str] = None,
) -> AuditLog:
    """Log an administrative action."""
    return await create_audit_log(
        admin_id=admin_id,
        action=action,
        target=target,
        details=details,
    )


# --- System config ---

async def get_system_config(key: str) -> Optional[str]:
    """Get system configuration value."""
    async with get_async_db() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()
        return config.value if config else None


async def set_system_config(key: str, value: str, description: str = "", is_secret: bool = False) -> SystemConfig:
    """Set system configuration value."""
    async with get_async_db() as db:
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        config = result.scalar_one_or_none()

        if config:
            config.value = value
            config.description = description
            config.is_secret = is_secret
            config.updated_at = datetime.utcnow()
        else:
            config = SystemConfig(
                key=key,
                value=value,
                description=description,
                is_secret=is_secret,
            )
            db.add(config)

        await db.commit()
        await db.refresh(config)
        return config


# --- Process state ---

async def save_process_state(bot_id: int, state: Dict[str, Any]) -> BotProcessState:
    """Save bot process state to database."""
    return await upsert_bot_process_state(bot_id, state)


async def get_process_state(bot_id: int) -> Optional[BotProcessState]:
    """Get bot process state from database."""
    return await get_bot_process_state(bot_id)


# --- Deployments ---

async def create_deployment(
    bot_id: int,
    version: Optional[str] = None,
    deployed_by: Optional[int] = None,
) -> Deployment:
    """Create a new deployment record."""
    async with get_async_db() as db:
        deployment = Deployment(
            bot_id=bot_id,
            version=version,
            deployed_by=deployed_by,
            status="pending",
            started_at=datetime.utcnow(),
        )
        db.add(deployment)
        await db.commit()
        await db.refresh(deployment)
        return deployment


async def update_deployment(
    deployment_id: int,
    status: Optional[str] = None,
    image_tag: Optional[str] = None,
    build_logs: Optional[str] = None,
) -> Optional[Deployment]:
    """Update deployment record."""
    async with get_async_db() as db:
        deployment = await db.get(Deployment, deployment_id)
        if deployment:
            if status is not None:
                deployment.status = status
            if image_tag is not None:
                deployment.image_tag = image_tag
            if build_logs is not None:
                deployment.build_logs = build_logs
            if status in ("success", "failed"):
                deployment.completed_at = datetime.utcnow()
            deployment.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(deployment)
        return deployment


async def get_deployments(bot_id: int, limit: int = 50) -> List[Deployment]:
    """Get deployments for a bot."""
    async with get_async_db() as db:
        result = await db.execute(
            select(Deployment)
            .where(Deployment.bot_id == bot_id)
            .order_by(Deployment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# --- Backups ---

async def create_backup_record(
    backup_type: str,
    file_path: Optional[str] = None,
) -> BackupRecord:
    """Create a new backup record."""
    async with get_async_db() as db:
        record = BackupRecord(
            backup_type=backup_type,
            status="pending",
            file_path=file_path,
            started_at=datetime.utcnow(),
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record


async def update_backup_record(
    backup_id: int,
    status: Optional[str] = None,
    file_path: Optional[str] = None,
    file_size_mb: Optional[int] = None,
    database_size_mb: Optional[int] = None,
    bots_included: Optional[int] = None,
    error_message: Optional[str] = None,
) -> Optional[BackupRecord]:
    """Update backup record."""
    async with get_async_db() as db:
        record = await db.get(BackupRecord, backup_id)
        if record:
            if status is not None:
                record.status = status
            if file_path is not None:
                record.file_path = file_path
            if file_size_mb is not None:
                record.file_size_mb = file_size_mb
            if database_size_mb is not None:
                record.database_size_mb = database_size_mb
            if bots_included is not None:
                record.bots_included = bots_included
            if error_message is not None:
                record.error_message = error_message
            if status in ("success", "failed"):
                record.completed_at = datetime.utcnow()
            record.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(record)
        return record


async def get_backup_records(limit: int = 50) -> List[BackupRecord]:
    """Get backup history."""
    async with get_async_db() as db:
        result = await db.execute(
            select(BackupRecord)
            .order_by(BackupRecord.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())