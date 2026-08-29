"""
Advanced notification system for bot events and monitoring.
Sends notifications to users and admins when important events occur.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from datetime import datetime
import logging
from abc import ABC, abstractmethod

from config import config
from logging_config import get_logger

logger = get_logger(__name__)


class NotificationLevel(str, Enum):
    """Notification severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationChannel(str, Enum):
    """Where to send notifications."""
    TELEGRAM = "telegram"
    EMAIL = "email"
    WEBHOOK = "webhook"
    LOG = "log"


class NotificationTemplate:
    """Template for notification messages."""
    
    TEMPLATES = {
        "bot_started": {
            "title": "✅ بوت تم تشغيله",
            "message": "البوت '{bot_name}' تم تشغيله بنجاح",
            "level": NotificationLevel.INFO,
        },
        "bot_stopped": {
            "title": "⏹️ بوت تم إيقافه",
            "message": "البوت '{bot_name}' تم إيقافه",
            "level": NotificationLevel.INFO,
        },
        "bot_crashed": {
            "title": "❌ بوت توقف بشكل غير متوقع",
            "message": "البوت '{bot_name}' توقف: {error}",
            "level": NotificationLevel.ERROR,
        },
        "bot_restarted": {
            "title": "🔄 بوت تم إعادة تشغيله",
            "message": "البوت '{bot_name}' تم إعادة تشغيله (محاولة {attempt}/{max_attempts})",
            "level": NotificationLevel.WARNING,
        },
        "crash_loop_detected": {
            "title": "⚠️ حلقة تعطل متكررة",
            "message": "البوت '{bot_name}' يدخل حلقة تعطل متكررة. توقف مؤقت لمدة {reset_seconds} ثانية",
            "level": NotificationLevel.CRITICAL,
        },
        "high_memory_usage": {
            "title": "💾 استخدام ذاكرة مرتفع",
            "message": "البوت '{bot_name}' يستخدم {memory_mb}MB من {max_memory_mb}MB المسموح",
            "level": NotificationLevel.WARNING,
        },
        "high_cpu_usage": {
            "title": "⚙️ استخدام CPU مرتفع",
            "message": "البوت '{bot_name}' يستخدم {cpu_percent}% من CPU",
            "level": NotificationLevel.WARNING,
        },
        "security_warning": {
            "title": "🔒 تحذير أمني",
            "message": "تم اكتشاف مشكلة أمنية في البوت '{bot_name}': {issue}",
            "level": NotificationLevel.CRITICAL,
        },
        "user_limit_exceeded": {
            "title": "📊 تجاوز حد العدد",
            "message": "المستخدم وصل لحد البوتات المسموح ({limit})",
            "level": NotificationLevel.WARNING,
        },
        "rate_limit_hit": {
            "title": "🚫 تم تجاو�� حد المعدل",
            "message": "المستخدم تجاوز حد الطلبات المسموح",
            "level": NotificationLevel.WARNING,
        },
    }
    
    @classmethod
    def get(cls, template_key: str) -> Optional[Dict]:
        """Get template by key."""
        return cls.TEMPLATES.get(template_key)
    
    @classmethod
    def format(cls, template_key: str, **kwargs) -> Dict[str, str]:
        """Format template with variables."""
        template = cls.get(template_key)
        if not template:
            return {"title": "إشعار", "message": "حدث حدث غير محدد"}
        
        return {
            "title": template["title"],
            "message": template["message"].format(**kwargs),
            "level": template["level"],
        }


class NotificationHandler(ABC):
    """Abstract base for notification handlers."""
    
    @abstractmethod
    async def send(
        self,
        user_id: int,
        title: str,
        message: str,
        level: NotificationLevel,
    ) -> bool:
        """Send notification. Returns True if successful."""
        pass


class TelegramNotificationHandler(NotificationHandler):
    """Send notifications via Telegram."""
    
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
    
    async def send(
        self,
        user_id: int,
        title: str,
        message: str,
        level: NotificationLevel,
    ) -> bool:
        """Send notification to user via Telegram."""
        try:
            # Emoji mapping for levels
            emojis = {
                NotificationLevel.INFO: "ℹ️",
                NotificationLevel.WARNING: "⚠️",
                NotificationLevel.ERROR: "❌",
                NotificationLevel.CRITICAL: "🔴",
            }
            
            emoji = emojis.get(level, "📢")
            full_message = f"{emoji} {title}\n\n{message}"
            
            # This would integrate with your Telegram bot
            logger.info(f"[TELEGRAM] User {user_id}: {full_message}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
            return False


class LogNotificationHandler(NotificationHandler):
    """Log notifications as records."""
    
    async def send(
        self,
        user_id: int,
        title: str,
        message: str,
        level: NotificationLevel,
    ) -> bool:
        """Log notification."""
        try:
            log_func = {
                NotificationLevel.INFO: logger.info,
                NotificationLevel.WARNING: logger.warning,
                NotificationLevel.ERROR: logger.error,
                NotificationLevel.CRITICAL: logger.critical,
            }.get(level, logger.info)
            
            log_func(f"[USER {user_id}] {title}: {message}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to log notification: {e}")
            return False


class NotificationManager:
    """Manage notifications across multiple channels."""
    
    def __init__(self):
        self.handlers: Dict[NotificationChannel, NotificationHandler] = {}
        self._initialize_handlers()
    
    def _initialize_handlers(self) -> None:
        """Initialize notification handlers."""
        self.handlers[NotificationChannel.TELEGRAM] = TelegramNotificationHandler(
            config.host_bot_token
        )
        self.handlers[NotificationChannel.LOG] = LogNotificationHandler()
    
    async def notify(
        self,
        user_id: int,
        template_key: str,
        channels: List[NotificationChannel] = None,
        **template_vars,
    ) -> bool:
        """
        Send notification using template.
        
        Args:
            user_id: Telegram user ID
            template_key: Template identifier
            channels: Where to send (default: all)
            **template_vars: Variables for template formatting
        
        Returns:
            True if at least one channel succeeded
        """
        if channels is None:
            channels = [NotificationChannel.TELEGRAM, NotificationChannel.LOG]
        
        # Format message
        formatted = NotificationTemplate.format(template_key, **template_vars)
        
        # Send via all channels
        results = []
        for channel in channels:
            if channel in self.handlers:
                try:
                    result = await self.handlers[channel].send(
                        user_id=user_id,
                        title=formatted["title"],
                        message=formatted["message"],
                        level=formatted["level"],
                    )
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error sending via {channel}: {e}")
                    results.append(False)
        
        return any(results)
    
    async def notify_bot_event(
        self,
        user_id: int,
        bot_name: str,
        event: str,
        **details,
    ) -> bool:
        """Shorthand for bot events."""
        template_vars = {
            "bot_name": bot_name,
            **details,
        }
        return await self.notify(user_id, event, **template_vars)
    
    async def notify_admin(
        self,
        title: str,
        message: str,
        level: NotificationLevel = NotificationLevel.INFO,
    ) -> bool:
        """Send notification to all admins."""
        results = []
        for admin_id in config.admin_ids:
            for channel in [NotificationChannel.TELEGRAM, NotificationChannel.LOG]:
                if channel in self.handlers:
                    try:
                        result = await self.handlers[channel].send(
                            user_id=admin_id,
                            title=title,
                            message=message,
                            level=level,
                        )
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Error notifying admin {admin_id}: {e}")
        
        return any(results)


# Global notification manager
_notification_manager = NotificationManager()


async def notify(
    user_id: int,
    template_key: str,
    **template_vars,
) -> bool:
    """Send notification to user."""
    return await _notification_manager.notify(user_id, template_key, **template_vars)


async def notify_bot_event(
    user_id: int,
    bot_name: str,
    event: str,
    **details,
) -> bool:
    """Send bot event notification."""
    return await _notification_manager.notify_bot_event(user_id, bot_name, event, **details)


async def notify_admins(
    title: str,
    message: str,
    level: NotificationLevel = NotificationLevel.INFO,
) -> bool:
    """Notify all admins."""
    return await _notification_manager.notify_admin(title, message, level)
