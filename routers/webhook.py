"""
Webhook endpoints for user bots.
Rate limited and secured.
"""

from __future__ import annotations

import logging
from typing import Dict, Any

from fastapi import APIRouter, Request, Response, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select

from config import config
from database import get_async_db, get_bot, get_env_vars, update_bot_status, save_process_state, get_system_config, set_system_config
from models import Bot
from middleware.rate_limit import rate_limit_webhook, limiter
from logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/{bot_token}")
@rate_limit_webhook("30/minute")
async def webhook_handler(
    bot_token: str,
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> Response:
    """
    Handle incoming webhook updates from Telegram.
    
    This endpoint receives updates from Telegram for user bots.
    The bot_token in the path identifies which bot the update is for.
    """
    # Find bot by token
    async with get_async_db() as db:
        # We need to search all bots for matching token
        # In production, you'd want an index on token or a separate lookup table
        result = await db.execute(
            select(Bot).where(Bot.id.isnot(None))  # Get all bots
        )
        bots = result.scalars().all()

    # Find matching bot
    bot = None
    for b in bots:
        env_vars = await get_env_vars(b.id)
        if env_vars.get("BOT_TOKEN") == bot_token:
            bot = b
            break

    if not bot:
        logger.warning("webhook_bot_not_found", token_prefix=bot_token[:10])
        raise HTTPException(status_code=404, detail="Bot not found")

    # Verify secret token if configured
    if x_telegram_bot_api_secret_token:
        expected_secret = await get_system_config(f"webhook_secret_{bot.id}")
        if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
            logger.warning("webhook_invalid_secret", bot_id=bot.id)
            raise HTTPException(status_code=403, detail="Invalid secret token")

    # Check bot status
    if bot.status != "running":
        logger.warning("webhook_bot_not_running", bot_id=bot.id, status=bot.status)
        return JSONResponse(
            status_code=200,
            content={"ok": False, "error": "Bot is not running"},
        )

    # Process update asynchronously
    # In production, you'd push to a queue (Redis/RabbitMQ) for workers to process
    try:
        update_data = await request.json()
        logger.info("webhook_received", bot_id=bot.id, update_id=update_data.get("update_id"))

        # TODO: Forward to bot process via message queue
        # For now, return OK - actual processing would be done by the bot process
        return JSONResponse(content={"ok": True})

    except Exception as e:
        logger.exception("webhook_processing_failed", bot_id=bot.id, error=str(e))
        return JSONResponse(
            status_code=200,  # Return 200 to prevent Telegram retries
            content={"ok": False, "error": "Processing failed"},
        )


@router.post("/{bot_token}/set")
@rate_limit_webhook("10/minute")
async def set_webhook(
    bot_token: str,
    request: Request,
) -> Dict[str, Any]:
    """
    Set webhook URL for a bot.
    """
    # Find bot by token
    async with get_async_db() as db:
        result = await db.execute(select(Bot))
        bots = result.scalars().all()

    bot = None
    for b in bots:
        env_vars = await get_env_vars(b.id)
        if env_vars.get("BOT_TOKEN") == bot_token:
            bot = b
            break

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Get webhook URL from request
    data = await request.json()
    webhook_url = data.get("url")

    if not webhook_url:
        raise HTTPException(status_code=400, detail="URL is required")

    # In production, you'd use the Telegram Bot API to set the webhook
    # For now, store the URL in bot config
    await set_system_config(f"webhook_url_{bot.id}", webhook_url)

    logger.info("webhook_set", bot_id=bot.id, url=webhook_url)

    return {"ok": True, "url": webhook_url}


@router.delete("/{bot_token}")
@rate_limit_webhook("10/minute")
async def delete_webhook(bot_token: str, request: Request) -> Dict[str, Any]:
    """Delete webhook for a bot."""
    async with get_async_db() as db:
        result = await db.execute(select(Bot))
        bots = result.scalars().all()

    bot = None
    for b in bots:
        env_vars = await get_env_vars(b.id)
        if env_vars.get("BOT_TOKEN") == bot_token:
            bot = b
            break

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    # Delete webhook via Telegram API
    # For now, just clear stored URL
    await set_system_config(f"webhook_url_{bot.id}", "")

    logger.info("webhook_deleted", bot_id=bot.id)

    return {"ok": True}


@router.get("/{bot_token}/info")
@rate_limit_webhook("30/minute")
async def webhook_info(bot_token: str, request: Request) -> Dict[str, Any]:
    """Get webhook info for a bot."""
    async with get_async_db() as db:
        result = await db.execute(select(Bot))
        bots = result.scalars().all()

    bot = None
    for b in bots:
        env_vars = await get_env_vars(b.id)
        if env_vars.get("BOT_TOKEN") == bot_token:
            bot = b
            break

    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")

    webhook_url = await get_system_config(f"webhook_url_{bot.id}")

    return {
        "url": webhook_url,
        "has_custom_certificate": False,
        "pending_update_count": 0,
        "max_connections": 40,
    }


# Need to import these for the webhook router
from sqlalchemy import select
from database import get_system_config, set_system_config