"""
Routers package for the Telegram Bot Hosting Platform.
"""

from . import health, webhook, api, admin, dashboard

__all__ = ["health", "webhook", "api", "admin", "dashboard"]