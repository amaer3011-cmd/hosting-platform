"""
Main application entry point - modular structure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from logging_config import setup_logging, get_logger
from database import init_db
from middleware.rate_limit import init_rate_limiter

# Import routers
from routers import health, webhook, api, admin, dashboard

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting Telegram Bot Hosting Platform")

    # Initialize logging
    setup_logging()

    # Initialize database
    init_db(config.DATABASE_URL)
    logger.info("Database initialized")

    # Initialize rate limiter
    init_rate_limiter(app)
    logger.info("Rate limiter initialized")

    # Create required directories
    Path(config.BOTS_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
    Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)

    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down Telegram Bot Hosting Platform")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Telegram Bot Hosting Platform",
        description="Production-ready platform for hosting Telegram bots",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if config.DEBUG else None,
        redoc_url="/api/redoc" if config.DEBUG else None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(health.router, tags=["Health"])
    app.include_router(webhook.router, prefix="/webhook", tags=["Webhook"])
    app.include_router(api.router, prefix="/api", tags=["API"])
    app.include_router(admin.router, prefix="/admin", tags=["Admin"])
    app.include_router(dashboard.router, tags=["Dashboard"])

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Templates
    templates_dir = Path(__file__).parent / "templates"
    if templates_dir.exists():
        app.state.templates = Jinja2Templates(directory=str(templates_dir))

    @app.get("/")
    async def root():
        return {
            "service": "Telegram Bot Hosting Platform",
            "version": "2.0.0",
            "status": "running",
            "docs": "/api/docs" if config.DEBUG else "disabled",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PORT,
        workers=1,  # Use 1 worker with async, scale horizontally
        reload=config.DEBUG,
        log_config=None,  # Use our custom logging
    )