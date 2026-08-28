from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    # =========================================================================
    # REQUIRED SETTINGS (no defaults - must be set in production)
    # =========================================================================
    
    # Bot settings
    host_bot_token: str = Field(..., alias="HOST_BOT_TOKEN", description="Telegram bot token for the hosting platform bot")
    admin_ids: tuple[int, ...] = Field(default_factory=tuple, alias="ADMIN_IDS", description="Comma-separated list of admin user IDs")
    bot_token_env_key: str = Field(default="BOT_TOKEN", alias="BOT_TOKEN_ENV_KEY")
    
    # Database - REQUIRED in production (PostgreSQL)
    database_url: str = Field(..., alias="DATABASE_URL", description="PostgreSQL async connection string: postgresql+asyncpg://user:pass@host:5432/db")
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE", ge=1, le=50)
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW", ge=0, le=100)
    
    # Redis - REQUIRED in production
    redis_url: str = Field(..., alias="REDIS_URL", description="Redis connection string: redis://:password@host:6379/0")
    
    # Security - REQUIRED in production
    encryption_key: str = Field(..., alias="ENCRYPTION_KEY", description="Base64-encoded 32-byte Fernet key for env var encryption")
    secret_key: str = Field(..., alias="SECRET_KEY", description="Flask/FastAPI secret key for sessions and signing")

    # =========================================================================
    # OPTIONAL SETTINGS (with production-safe defaults)
    # =========================================================================
    
    # Environment
    environment: str = Field(default="development", alias="ENVIRONMENT", description="Environment: development, staging, production")
    debug: bool = Field(default=False, alias="DEBUG")
    port: int = Field(default=8080, alias="PORT", ge=1, le=65535)
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")
    
    # Domain (for SSL/Traefik)
    domain: Optional[str] = Field(default=None, alias="DOMAIN", description="Primary domain for the platform")
    
    # File paths
    base_dir: Path = Path(__file__).resolve().parent
    bots_dir: Path = Field(default=Path("./uploaded_bots"), alias="BOTS_DIR")
    backup_dir: Path = Field(default=Path("./backups"), alias="BACKUP_DIR")
    log_dir: Path = Field(default=Path("./logs"), alias="LOG_DIR")
    
    # Limits
    max_file_size_mb: int = Field(default=50, alias="MAX_FILE_SIZE_MB", ge=1, le=500)
    max_extracted_size_mb: int = Field(default=200, alias="MAX_EXTRACTED_SIZE_MB", ge=10, le=2000)
    max_zip_file_count: int = Field(default=2000, alias="MAX_ZIP_FILE_COUNT", ge=100, le=10000)
    max_bot_memory_mb: int = Field(default=1024, alias="MAX_BOT_MEMORY_MB", ge=128, le=8192)
    max_bot_cpu_seconds: int = Field(default=3600, alias="MAX_BOT_CPU_SECONDS", ge=60, le=86400)
    default_max_bots: int = Field(default=3, alias="DEFAULT_MAX_BOTS", ge=1, le=50)
    max_auto_restart_attempts: int = Field(default=5, alias="MAX_AUTO_RESTART_ATTEMPTS", ge=0, le=20)
    crash_loop_reset_seconds: int = Field(default=300, alias="CRASH_LOOP_RESET_SECONDS", ge=60, le=3600)
    restart_backoff_base_seconds: int = Field(default=5, alias="RESTART_BACKOFF_BASE_SECONDS", ge=1, le=60)
    venv_setup_timeout_seconds: int = Field(default=300, alias="VENV_SETUP_TIMEOUT_SECONDS", ge=30, le=1800)
    max_concurrent_venv_setups: int = Field(default=2, alias="MAX_CONCURRENT_VENV_SETUPS", ge=1, le=10)
    max_log_size_mb: int = Field(default=10, alias="MAX_LOG_SIZE_MB", ge=1, le=100)
    log_tail_lines: int = Field(default=100, alias="LOG_TAIL_LINES", ge=10, le=1000)
    
    # Intervals
    watchdog_interval: int = Field(default=20, alias="WATCHDOG_INTERVAL", ge=5, le=300)
    cleanup_interval_seconds: int = Field(default=300, alias="CLEANUP_INTERVAL_SECONDS", ge=60, le=3600)
    usage_history_interval_seconds: int = Field(default=300, alias="USAGE_HISTORY_INTERVAL_SECONDS", ge=60, le=3600)
    usage_history_max_points: int = Field(default=50, alias="USAGE_HISTORY_MAX_POINTS", ge=10, le=500)
    health_check_timeout_seconds: int = Field(default=6, alias="HEALTH_CHECK_TIMEOUT_SECONDS", ge=1, le=30)
    
    # Rate limiting
    rate_limit_msgs_per_minute: int = Field(default=30, alias="RATE_LIMIT_MSGS_PER_MINUTE", ge=1, le=1000)
    internal_api_key: str = Field(default="", alias="INTERNAL_API_KEY")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    
    # Restart scheduling
    restart_interval_choices_hours: tuple[int, ...] = (0, 6, 12, 24, 48)
    
    # Docker
    use_docker: bool = Field(default=True, alias="USE_DOCKER")
    docker_socket: str = Field(default="/var/run/docker.sock", alias="DOCKER_SOCKET")
    docker_memory_limit_mb: int = Field(default=1024, alias="DOCKER_MEMORY_LIMIT_MB", ge=128, le=8192)
    docker_cpu_limit: float = Field(default=1.0, alias="DOCKER_CPU_LIMIT", ge=0.1, le=8.0)
    
    # Dashboard
    dashboard_enabled: bool = Field(default=True, alias="DASHBOARD_ENABLED")
    dashboard_port: int = Field(default=8000, alias="DASHBOARD_PORT")
    dashboard_host: str = Field(default="0.0.0.0", alias="DASHBOARD_HOST")
    
    # API
    api_port: int = Field(default=8000, alias="API_PORT")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_workers: int = Field(default=4, alias="API_WORKERS", ge=1, le=16)
    
    # AI Analysis
    ai_analysis_enabled: bool = Field(default=True, alias="AI_ANALYSIS_ENABLED")
    ai_max_file_size_kb: int = Field(default=512, alias="AI_MAX_FILE_SIZE_KB", ge=10, le=2048)
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    
    # Backup
    backup_retention_count: int = Field(default=14, alias="BACKUP_RETENTION_COUNT", ge=1, le=90)
    backup_interval_seconds: int = Field(default=3600, alias="BACKUP_INTERVAL_SECONDS", ge=300, le=86400)
    backup_db: bool = Field(default=True, alias="BACKUP_DB")
    backup_bots: bool = Field(default=True, alias="BACKUP_BOTS")
    backup_logs: bool = Field(default=True, alias="BACKUP_LOGS")
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")  # json or console
    sentry_dsn: Optional[str] = Field(default=None, alias="SENTRY_DSN")
    
    # Monitoring
    prometheus_enabled: bool = Field(default=True, alias="PROMETHEUS_ENABLED")
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")

    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return tuple(int(x.strip()) for x in v.split(",") if x.strip().isdigit())
        if isinstance(v, (list, tuple)):
            return tuple(int(x) for x in v)
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return v.upper()

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, v):
        if v.lower() not in {"json", "console"}:
            raise ValueError("LOG_FORMAT must be 'json' or 'console'")
        return v.lower()

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v):
        valid = {"development", "staging", "production"}
        if v.lower() not in valid:
            raise ValueError(f"ENVIRONMENT must be one of {valid}")
        return v.lower()

    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, v):
        """Validate Fernet key format."""
        import base64
        try:
            decoded = base64.urlsafe_b64decode(v)
            if len(decoded) != 32:
                raise ValueError
        except Exception:
            raise ValueError("ENCRYPTION_KEY must be a valid base64-encoded 32-byte key")
        return v

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bots_dir = self.bots_dir.resolve()
        self.bots_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir = self.backup_dir.resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        (self.backup_dir / "db").mkdir(exist_ok=True)
        (self.backup_dir / "bots").mkdir(exist_ok=True)
        (self.backup_dir / "logs").mkdir(exist_ok=True)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def database_async_url(self) -> str:
        """Get async database URL for SQLAlchemy."""
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()

# =========================================================================
# BACKWARD COMPATIBILITY ALIASES (for existing code)
# =========================================================================
HOST_BOT_TOKEN = settings.host_bot_token
ADMIN_IDS = settings.admin_ids
BOTS_DIR = settings.bots_dir
BACKUP_DIR = settings.backup_dir
LOG_DIR = settings.log_dir
DB_PATH = Path(settings.database_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", ""))
DATABASE_URL = settings.database_url
REDIS_URL = settings.redis_url
PORT = settings.port
DEBUG = settings.debug
CORS_ORIGINS = [item.strip() for item in settings.cors_origins.split(",") if item.strip()] or ["*"]
DB_POOL_SIZE = settings.db_pool_size
DB_MAX_OVERFLOW = settings.db_max_overflow
BOT_TOKEN_ENV_KEY = settings.bot_token_env_key
INTERNAL_API_KEY = settings.internal_api_key
RATE_LIMIT_REQUESTS_PER_MINUTE = settings.rate_limit_msgs_per_minute
MAX_FILE_SIZE_MB = settings.max_file_size_mb
MAX_EXTRACTED_SIZE_MB = settings.max_extracted_size_mb
MAX_ZIP_FILE_COUNT = settings.max_zip_file_count
MAX_BOT_MEMORY_MB = settings.max_bot_memory_mb
MAX_BOT_CPU_SECONDS = settings.max_bot_cpu_seconds
DEFAULT_MAX_BOTS = settings.default_max_bots
MAX_AUTO_RESTART_ATTEMPTS = settings.max_auto_restart_attempts
CRASH_LOOP_RESET_SECONDS = settings.crash_loop_reset_seconds
RESTART_BACKOFF_BASE_SECONDS = settings.restart_backoff_base_seconds
VENV_SETUP_TIMEOUT_SECONDS = settings.venv_setup_timeout_seconds
MAX_CONCURRENT_VENV_SETUPS = settings.max_concurrent_venv_setups
MAX_LOG_SIZE_MB = settings.max_log_size_mb
LOG_TAIL_LINES = settings.log_tail_lines
WATCHDOG_INTERVAL = settings.watchdog_interval
CLEANUP_INTERVAL_SECONDS = settings.cleanup_interval_seconds
USAGE_HISTORY_INTERVAL_SECONDS = settings.usage_history_interval_seconds
USAGE_HISTORY_MAX_POINTS = settings.usage_history_max_points
HEALTH_CHECK_TIMEOUT_SECONDS = settings.health_check_timeout_seconds
RATE_LIMIT_MSGS_PER_MINUTE = settings.rate_limit_msgs_per_minute
ENCRYPTION_KEY = settings.encryption_key
USE_DOCKER = settings.use_docker
DOCKER_SOCKET = settings.docker_socket
DASHBOARD_ENABLED = settings.dashboard_enabled
DASHBOARD_PORT = settings.dashboard_port
DASHBOARD_HOST = settings.dashboard_host
USE_POSTGRESQL = True  # Force PostgreSQL in production
USE_REDIS = True  # Force Redis in production
AI_ANALYSIS_ENABLED = settings.ai_analysis_enabled
AI_MAX_FILE_SIZE_KB = settings.ai_max_file_size_kb
PROTECTED_ENV_KEYS = frozenset({
    "PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONHOME",
    "PYTHONPATH", "PYTHONSTARTUP", "HOME", "USER", "SHELL"
})
RESTART_INTERVAL_CHOICES_HOURS = settings.restart_interval_choices_hours

# Existing modules import `config` as an object and use uppercase names.
# Keep that API while retaining Pydantic Settings as the source of truth.
config = settings
for _name in (
    "HOST_BOT_TOKEN", "ADMIN_IDS", "BOTS_DIR", "BACKUP_DIR", "LOG_DIR",
    "DB_PATH", "DATABASE_URL", "REDIS_URL", "PORT", "DEBUG", "CORS_ORIGINS",
    "DB_POOL_SIZE", "DB_MAX_OVERFLOW", "BOT_TOKEN_ENV_KEY", "INTERNAL_API_KEY",
    "RATE_LIMIT_REQUESTS_PER_MINUTE", "MAX_FILE_SIZE_MB", "MAX_EXTRACTED_SIZE_MB",
    "MAX_ZIP_FILE_COUNT", "MAX_BOT_MEMORY_MB", "MAX_BOT_CPU_SECONDS",
    "DEFAULT_MAX_BOTS", "MAX_AUTO_RESTART_ATTEMPTS", "CRASH_LOOP_RESET_SECONDS",
    "RESTART_BACKOFF_BASE_SECONDS", "VENV_SETUP_TIMEOUT_SECONDS",
    "MAX_CONCURRENT_VENV_SETUPS", "MAX_LOG_SIZE_MB", "LOG_TAIL_LINES",
    "WATCHDOG_INTERVAL", "CLEANUP_INTERVAL_SECONDS", "USAGE_HISTORY_INTERVAL_SECONDS",
    "USAGE_HISTORY_MAX_POINTS", "HEALTH_CHECK_TIMEOUT_SECONDS",
    "RATE_LIMIT_MSGS_PER_MINUTE", "ENCRYPTION_KEY", "USE_DOCKER", "DOCKER_SOCKET",
    "DASHBOARD_ENABLED", "DASHBOARD_PORT", "DASHBOARD_HOST", "USE_POSTGRESQL",
    "USE_REDIS", "AI_ANALYSIS_ENABLED", "AI_MAX_FILE_SIZE_KB", "PROTECTED_ENV_KEYS",
    "RESTART_INTERVAL_CHOICES_HOURS",
):
    object.__setattr__(config, _name, globals()[_name])