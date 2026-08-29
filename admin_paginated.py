"""
Enhanced admin router with pagination support.
Replaces previous admin panel with paginated lists.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
import logging

from database import (
    get_users_page,
    get_audit_log_page,
    get_all_bots,
    global_stats,
    ban_user,
)
from pagination import PaginationParams, PaginatedResponse, paginate_async
from config import config

logger = logging.getLogger(__name__)
router = APIRouter()


async def verify_admin(user_id: int) -> bool:
    """Verify user is admin."""
    return user_id in config.admin_ids


@router.get("/stats")
async def get_stats():
    """Get global platform statistics."""
    stats = await global_stats()
    return {
        "status": "success",
        "data": stats,
    }


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """
    Get paginated list of users.
    
    Query Parameters:
        - page: Page number (1-indexed)
        - per_page: Items per page (max 100)
    """
    users, total = await get_users_page(page, per_page)
    
    response = PaginatedResponse.create(
        items=[
            {
                "id": u.id,
                "username": u.username,
                "first_name": u.first_name,
                "is_banned": u.is_banned,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ],
        total=total,
        page=page,
        per_page=per_page,
    )
    
    return {
        "status": "success",
        "data": response.to_dict(),
    }


@router.get("/audit-log")
async def get_audit_log(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """
    Get paginated audit log.
    
    Query Parameters:
        - page: Page number (1-indexed)
        - per_page: Items per page (max 100)
    """
    logs, total = await get_audit_log_page(page, per_page)
    
    response = PaginatedResponse.create(
        items=[
            {
                "id": log.id,
                "admin_id": log.admin_id,
                "action": log.action,
                "target": log.target,
                "details": log.details,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
        total=total,
        page=page,
        per_page=per_page,
    )
    
    return {
        "status": "success",
        "data": response.to_dict(),
    }


@router.get("/bots")
async def list_all_bots(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """
    Get paginated list of all bots (admin only).
    
    Query Parameters:
        - page: Page number (1-indexed)
        - per_page: Items per page (max 100)
    """
    all_bots = await get_all_bots()
    
    # Manual pagination for simplicity
    params = PaginationParams(page=page, per_page=per_page)
    start = params.offset
    end = start + params.limit
    
    paginated_bots = all_bots[start:end]
    
    response = PaginatedResponse.create(
        items=[
            {
                "id": bot.id,
                "owner_id": bot.owner_id,
                "name": bot.name,
                "status": bot.status,
                "created_at": bot.created_at.isoformat(),
            }
            for bot in paginated_bots
        ],
        total=len(all_bots),
        page=page,
        per_page=per_page,
    )
    
    return {
        "status": "success",
        "data": response.to_dict(),
    }


@router.post("/ban-user/{user_id}")
async def ban_user_endpoint(user_id: int, reason: Optional[str] = None):
    """Ban a user from the platform."""
    success = await ban_user(user_id, banned=True)
    
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "status": "success",
        "message": f"User {user_id} has been banned",
        "reason": reason,
    }


@router.post("/unban-user/{user_id}")
async def unban_user_endpoint(user_id: int):
    """Unban a user from the platform."""
    success = await ban_user(user_id, banned=False)
    
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "status": "success",
        "message": f"User {user_id} has been unbanned",
    }
