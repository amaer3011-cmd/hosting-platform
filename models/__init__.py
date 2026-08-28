"""
SQLAlchemy models for the Telegram Bot Hosting Platform.
Production-ready with async support, proper indexes, and constraints.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    BigInteger,
    ForeignKey,
    Index,
    UniqueConstraint,
    CheckConstraint,
    event,
)
from sqlalchemy.orm import (
    declarative_base,
    relationship,
    sessionmaker,
    Session,
    declared_attr,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON

from config import config

Base = declarative_base()


class TimestampMixin:
    """Mixin for created_at / updated_at timestamps."""
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class User(Base, TimestampMixin):
    """Platform user (Telegram user who hosts bots)."""
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_username", "username"),
        Index("ix_users_is_banned", "is_banned"),
        Index("ix_users_created_at", "created_at"),
        CheckConstraint("max_bots > 0", name="ck_users_max_bots_positive"),
    )

    id = Column(BigInteger, primary_key=True)  # Telegram user_id
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    language_code = Column(String(10), nullable=True)
    is_banned = Column(Boolean, default=False, nullable=False)
    max_bots = Column(Integer, default=10, nullable=False)

    # Relationships
    bots = relationship("Bot", back_populates="owner", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="admin")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "language_code": self.language_code,
            "is_banned": self.is_banned,
            "max_bots": self.max_bots,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Bot(Base, TimestampMixin):
    """User's bot instance."""
    __tablename__ = "bots"
    __table_args__ = (
        Index("ix_bots_owner_id", "owner_id"),
        Index("ix_bots_status", "status"),
        Index("ix_bots_name", "name"),
        Index("ix_bots_created_at", "created_at"),
        CheckConstraint("restart_interval_hours >= 0", name="ck_bots_restart_interval_nonneg"),
        CheckConstraint("max_memory_mb >= 128", name="ck_bots_min_memory"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    folder = Column(String(512), nullable=True)
    entry_file = Column(String(512), nullable=True)
    status = Column(String(32), default="stopped", nullable=False)  # stopped, running, crashed, starting, stopping
    max_memory_mb = Column(Integer, nullable=True)  # None = use default
    restart_interval_hours = Column(Integer, default=0, nullable=False)  # 0 = disabled
    auto_restart = Column(Boolean, default=True, nullable=False)
    last_started_at = Column(DateTime, nullable=True)
    last_stopped_at = Column(DateTime, nullable=True)
    crash_count = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)

    # Relationships
    owner = relationship("User", back_populates="bots")
    env_vars = relationship("EnvVar", back_populates="bot", cascade="all, delete-orphan")
    process_state = relationship("BotProcessState", back_populates="bot", uselist=False, cascade="all, delete-orphan")
    deployments = relationship("Deployment", back_populates="bot", cascade="all, delete-orphan")

    def to_dict(self, include_env: bool = False) -> Dict[str, Any]:
        result = {
            "bot_id": self.id,
            "owner_id": self.owner_id,
            "name": self.name,
            "folder": self.folder,
            "entry_file": self.entry_file,
            "status": self.status,
            "max_memory_mb": self.max_memory_mb,
            "restart_interval_hours": self.restart_interval_hours,
            "auto_restart": self.auto_restart,
            "last_started_at": self.last_started_at.isoformat() if self.last_started_at else None,
            "last_stopped_at": self.last_stopped_at.isoformat() if self.last_stopped_at else None,
            "crash_count": self.crash_count,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_env:
            result["env_vars"] = {ev.key: ev.value for ev in self.env_vars}
        return result


class EnvVar(Base):
    """Environment variable for a bot (encrypted at rest)."""
    __tablename__ = "env_vars"
    __table_args__ = (
        UniqueConstraint("bot_id", "key", name="uq_env_vars_bot_key"),
        Index("ix_env_vars_bot_id", "bot_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(255), nullable=False)
    value_encrypted = Column(Text, nullable=False)  # Fernet encrypted
    display_value = Column(String(255), nullable=True)  # Masked for display

    # Relationships
    bot = relationship("Bot", back_populates="env_vars")


class BotProcessState(Base, TimestampMixin):
    """Persistent process state for bot containers/processes."""
    __tablename__ = "bot_process_state"
    __table_args__ = (
        Index("ix_bot_process_state_status", "status"),
        Index("ix_bot_process_state_last_heartbeat", "last_heartbeat"),
    )

    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True)
    container_id = Column(String(64), nullable=True)
    pid = Column(Integer, nullable=True)
    status = Column(String(32), default="unknown", nullable=False)  # unknown, starting, running, stopping, stopped, crashed, restarting
    started_at = Column(DateTime, nullable=True)
    last_heartbeat = Column(DateTime, nullable=True)
    restart_count = Column(Integer, default=0, nullable=False)
    cpu_percent = Column(String(32), nullable=True)
    memory_percent = Column(String(32), nullable=True)
    memory_mb = Column(Integer, nullable=True)
    exit_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)

    # Relationships
    bot = relationship("Bot", back_populates="process_state")


class Deployment(Base, TimestampMixin):
    """Deployment history for bots."""
    __tablename__ = "deployments"
    __table_args__ = (
        Index("ix_deployments_bot_id", "bot_id"),
        Index("ix_deployments_status", "status"),
        Index("ix_deployments_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
    version = Column(String(64), nullable=True)  # git commit, tag, or timestamp
    status = Column(String(32), default="pending", nullable=False)  # pending, building, success, failed
    image_tag = Column(String(255), nullable=True)
    build_logs = Column(Text, nullable=True)
    deployed_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    bot = relationship("Bot", back_populates="deployments")
    deployer = relationship("User")


class AuditLog(Base, TimestampMixin):
    """Audit log for administrative actions."""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_admin_id", "admin_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_target", "target"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    admin_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(64), nullable=False)
    target = Column(String(255), nullable=True)  # bot_id, user_id, etc.
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(512), nullable=True)

    # Relationships
    admin = relationship("User", back_populates="audit_logs")


class BackupRecord(Base, TimestampMixin):
    """Backup history and metadata."""
    __tablename__ = "backup_records"
    __table_args__ = (
        Index("ix_backup_records_status", "status"),
        Index("ix_backup_records_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    backup_type = Column(String(32), nullable=False)  # full, incremental, schema_only
    status = Column(String(32), default="pending", nullable=False)  # pending, running, success, failed
    file_path = Column(String(512), nullable=True)
    file_size_mb = Column(Integer, nullable=True)
    database_size_mb = Column(Integer, nullable=True)
    bots_included = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "backup_type": self.backup_type,
            "status": self.status,
            "file_path": self.file_path,
            "file_size_mb": self.file_size_mb,
            "database_size_mb": self.database_size_mb,
            "bots_included": self.bots_included,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SystemConfig(Base):
    """System-wide configuration (key-value store)."""
    __tablename__ = "system_config"
    __table_args__ = (
        UniqueConstraint("key", name="uq_system_config_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(128), nullable=False)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    is_secret = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value if not self.is_secret else "***",
            "description": self.description,
            "is_secret": self.is_secret,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# --- Database session management ---

engine = None
SessionLocal = None
AsyncSessionLocal = None


def init_db(database_url: Optional[str] = None) -> None:
    """Initialize database engine and create tables."""
    global engine, SessionLocal, AsyncSessionLocal

    if database_url is None:
        database_url = config.DATABASE_URL

    if database_url.startswith("postgresql"):
        # PostgreSQL with asyncpg
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.pool import NullPool

        # Convert to async URL if needed
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif database_url.startswith("postgresql+psycopg2://"):
            database_url = database_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)

        engine = create_async_engine(
            database_url,
            pool_size=config.DB_POOL_SIZE,
            max_overflow=config.DB_MAX_OVERFLOW,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Also create sync engine for migrations
        from sqlalchemy import create_engine
        sync_url = database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
        sync_engine = create_engine(sync_url, pool_pre_ping=True)
        Base.metadata.create_all(sync_engine)
    else:
        # SQLite (development only)
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        if database_url.startswith("sqlite:///"):
            db_path = database_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
            poolclass=StaticPool if database_url.startswith("sqlite") else None,
        )
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(engine)


def get_db() -> Session:
    """Get synchronous database session."""
    if SessionLocal is None:
        init_db()
    return SessionLocal()


async def get_async_db() -> AsyncSession:
    """Get asynchronous database session."""
    if AsyncSessionLocal is None:
        init_db()
    return AsyncSessionLocal()


# --- Helper functions ---

async def upsert_bot_process_state(bot_id: int, state: Dict[str, Any]) -> BotProcessState:
    """Create or update bot process state."""
    async with get_async_db() as db:
        process_state = await db.get(BotProcessState, bot_id)
        if process_state is None:
            process_state = BotProcessState(bot_id=bot_id)
            db.add(process_state)

        for key, value in state.items():
            if hasattr(process_state, key):
                setattr(process_state, key, value)

        process_state.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(process_state)
        return process_state


async def get_bot_process_state(bot_id: int) -> Optional[BotProcessState]:
    """Get bot process state by bot ID."""
    async with get_async_db() as db:
        return await db.get(BotProcessState, bot_id)


async def get_running_bots() -> List[Bot]:
    """Get all bots with running status."""
    async with get_async_db() as db:
        from sqlalchemy import select
        result = await db.execute(select(Bot).where(Bot.status == "running"))
        return list(result.scalars().all())


async def update_bot_status(bot_id: int, status: str, error: Optional[str] = None) -> None:
    """Update bot status and optionally record error."""
    async with get_async_db() as db:
        bot = await db.get(Bot, bot_id)
        if bot:
            bot.status = status
            bot.updated_at = datetime.utcnow()
            if error:
                bot.last_error = error
                bot.crash_count += 1
            if status == "running":
                bot.last_started_at = datetime.utcnow()
            elif status in ("stopped", "crashed"):
                bot.last_stopped_at = datetime.utcnow()
            await db.commit()


async def create_audit_log(
    admin_id: Optional[int],
    action: str,
    target: Optional[str] = None,
    details: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> AuditLog:
    """Create an audit log entry."""
    async with get_async_db() as db:
        log = AuditLog(
            admin_id=admin_id,
            action=action,
            target=target,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(log)
        await db.commit()
        await db.refresh(log)
        return log


async def get_bot_with_relations(bot_id: int) -> Optional[Bot]:
    """Get bot with all relationships loaded."""
    async with get_async_db() as db:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        result = await db.execute(
            select(Bot)
            .options(
                selectinload(Bot.env_vars),
                selectinload(Bot.process_state),
                selectinload(Bot.owner),
            )
            .where(Bot.id == bot_id)
        )
        return result.scalar_one_or_none()


# --- Event listeners for auto-updating timestamps ---

@event.listens_for(User, "before_update")
@event.listens_for(Bot, "before_update")
@event.listens_for(BotProcessState, "before_update")
@event.listens_for(Deployment, "before_update")
@event.listens_for(BackupRecord, "before_update")
def update_timestamp(mapper, connection, target):
    target.updated_at = datetime.utcnow()