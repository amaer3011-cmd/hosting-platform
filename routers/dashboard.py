"""
Dashboard web UI endpoints (serves the admin panel HTML).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from config import config
from database import get_async_db, get_user, get_user_bots, global_stats, get_all_bots
from models import User, Bot
from middleware.rate_limit import rate_limit_admin
from logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


# Templates will be set by main app
templates: Optional[Jinja2Templates] = None


def get_templates(request: Request) -> Jinja2Templates:
    """Get templates from app state."""
    if not request.app.state.templates:
        raise HTTPException(status_code=500, detail="Templates not configured")
    return request.app.state.templates


# --- Dependency for authenticated user (session-based) ---
async def get_current_user_from_session(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """Get current user from session cookie."""
    # In production, use proper session management (JWT, encrypted cookies, etc.)
    # For now, use a simple approach with user_id in session
    user_id = request.session.get("user_id") if hasattr(request, "session") else None

    # Fallback to query param for development
    if not user_id:
        user_id = request.query_params.get("user_id")
        if user_id:
            try:
                user_id = int(user_id)
            except ValueError:
                user_id = None

    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="User is banned")

    return user


async def get_admin_user_from_session(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """Get admin user from session."""
    user = await get_current_user_from_session(request, db)
    if user.id not in config.ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# --- Dashboard pages ---

@router.get("/", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    user: User = Depends(get_current_user_from_session),
    db: AsyncSession = Depends(get_async_db),
):
    """Main dashboard page for users."""
    tmpl = get_templates(request)
    bots = await get_user_bots(user.id)

    # Get running count
    from process_manager import manager
    running_count = sum(1 for bot in bots if manager().is_running(bot.id))

    return tmpl.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "bots": bots,
            "running_count": running_count,
            "total_bots": len(bots),
            "max_bots": user.max_bots,
            "is_admin": user.id in config.ADMIN_IDS,
        },
    )


@router.get("/bot/{bot_id}", response_class=HTMLResponse)
async def dashboard_bot_detail(
    bot_id: int,
    request: Request,
    user: User = Depends(get_current_user_from_session),
    db: AsyncSession = Depends(get_async_db),
):
    """Bot detail page."""
    tmpl = get_templates(request)
    bot = await get_bot_full(bot_id)

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    if bot.owner_id != user.id and user.id not in config.ADMIN_IDS:
        raise HTTPException(status_code=403, detail="Not authorized")

    from database import list_env_vars, get_deployments
    env_vars = await list_env_vars(bot_id)
    deployments = await get_deployments(bot_id)

    return tmpl.TemplateResponse(
        "bot_detail.html",
        {
            "request": request,
            "user": user,
            "bot": bot,
            "env_vars": env_vars,
            "deployments": deployments,
            "is_admin": user.id in config.ADMIN_IDS,
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    tmpl = get_templates(request)
    return tmpl.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """Handle login (simplified - in production use proper auth)."""
    user = await get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid user ID")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="User is banned")

    # Set session
    request.session["user_id"] = user_id
    return RedirectResponse(url="/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    """Logout."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


# --- Admin dashboard pages ---

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin: User = Depends(get_admin_user_from_session),
    db: AsyncSession = Depends(get_async_db),
):
    """Admin dashboard."""
    tmpl = get_templates(request)
    stats = await global_stats()

    return tmpl.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "admin": admin,
            "stats": stats,
        },
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin: User = Depends(get_admin_user_from_session),
    db: AsyncSession = Depends(get_async_db),
    page: int = 1,
):
    """Admin users list."""
    tmpl = get_templates(request)
    from database import get_users_page, count_user_bots

    users, total = await get_users_page(page, 50)

    # Add bot counts
    user_data = []
    for user in users:
        bot_count = await count_user_bots(user.id)
        user_data.append({"user": user, "bot_count": bot_count})

    total_pages = (total + 49) // 50

    return tmpl.TemplateResponse(
        "admin/users.html",
        {
            "request": request,
            "admin": admin,
            "users": user_data,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@router.get("/admin/bots", response_class=HTMLResponse)
async def admin_bots(
    request: Request,
    admin: User = Depends(get_admin_user_from_session),
    db: AsyncSession = Depends(get_async_db),
    page: int = 1,
    status: Optional[str] = None,
):
    """Admin bots list."""
    tmpl = get_templates(request)

    bots = await get_all_bots()
    if status:
        bots = [b for b in bots if b.status == status]

    # Pagination
    per_page = 50
    total = len(bots)
    total_pages = (total + per_page - 1) // per_page
    offset = (page - 1) * per_page
    bots_page = bots[offset:offset + per_page]

    return tmpl.TemplateResponse(
        "admin/bots.html",
        {
            "request": request,
            "admin": admin,
            "bots": bots_page,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "status_filter": status,
        },
    )


@router.get("/admin/audit-logs", response_class=HTMLResponse)
async def admin_audit_logs(
    request: Request,
    admin: User = Depends(get_admin_user_from_session),
    db: AsyncSession = Depends(get_async_db),
    page: int = 1,
):
    """Admin audit logs."""
    tmpl = get_templates(request)
    from database import get_audit_log_page

    logs, total = await get_audit_log_page(page, 50)
    total_pages = (total + 49) // 50

    return tmpl.TemplateResponse(
        "admin/audit_logs.html",
        {
            "request": request,
            "admin": admin,
            "logs": logs,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@router.get("/admin/backups", response_class=HTMLResponse)
async def admin_backups(
    request: Request,
    admin: User = Depends(get_admin_user_from_session),
    db: AsyncSession = Depends(get_async_db),
):
    """Admin backups."""
    tmpl = get_templates(request)
    from database import get_backup_records

    backups = await get_backup_records(50)

    return tmpl.TemplateResponse(
        "admin/backups.html",
        {
            "request": request,
            "admin": admin,
            "backups": backups,
        },
    )


@router.get("/admin/config", response_class=HTMLResponse)
async def admin_config(
    request: Request,
    admin: User = Depends(get_admin_user_from_session),
    db: AsyncSession = Depends(get_async_db),
):
    """Admin system configuration."""
    tmpl = get_templates(request)

    async with get_async_db() as db:
        result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
        configs = result.scalars().all()

    return tmpl.TemplateResponse(
        "admin/config.html",
        {
            "request": request,
            "admin": admin,
            "configs": configs,
        },
    )


# Need imports
from models import SystemConfig
from database import get_bot_full