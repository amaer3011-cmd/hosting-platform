"""
Log rotation and archival system for efficient storage management.
Automatically archives old logs and manages disk space.
"""

from __future__ import annotations

import gzip
import shutil
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

from config import config
from logging_config import get_logger

logger = get_logger(__name__)


class LogRotationManager:
    """Manage log rotation, compression, and archival."""
    
    def __init__(self):
        self.logs_dir = Path(config.LOG_DIR)
        self.bots_dir = Path(config.BOTS_DIR)
        self.archive_dir = Path(config.BACKUP_DIR) / "logs_archive"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_log_size_mb = config.max_log_size_mb
        self.max_log_age_days = 30  # Default retention
    
    async def rotate_bot_logs(self, bot_id: int, bot_folder: str) -> bool:
        """
        Rotate logs for a specific bot.
        
        Args:
            bot_id: Bot ID
            bot_folder: Bot folder path
        
        Returns:
            True if rotation successful
        """
        try:
            bot_path = self.bots_dir / bot_folder
            log_file = bot_path / "run.log"
            
            if not log_file.exists():
                return True
            
            # Check file size
            file_size_mb = log_file.stat().st_size / (1024 * 1024)
            
            if file_size_mb > self.max_log_size_mb:
                await self._rotate_file(log_file, bot_id)
                logger.info(f"Rotated log for bot {bot_id}")
                return True
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to rotate logs for bot {bot_id}: {e}")
            return False
    
    async def _rotate_file(self, log_file: Path, bot_id: int) -> None:
        """Rotate a single log file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Archive old log
        archive_name = f"bot_{bot_id}_{timestamp}.log.gz"
        archive_path = self.archive_dir / archive_name
        
        # Compress and move
        with open(log_file, 'rb') as f_in:
            with gzip.open(archive_path, 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Clear original log
        log_file.write_text("")
        
        logger.info(f"Archived log to {archive_path}")
    
    async def cleanup_old_logs(self, max_age_days: Optional[int] = None) -> int:
        """
        Delete archived logs older than max_age_days.
        
        Args:
            max_age_days: Max age in days (uses default if None)
        
        Returns:
            Number of files deleted
        """
        if max_age_days is None:
            max_age_days = self.max_log_age_days
        
        cutoff_date = datetime.now() - timedelta(days=max_age_days)
        deleted_count = 0
        
        try:
            for archive_file in self.archive_dir.glob("*.log.gz"):
                file_mtime = datetime.fromtimestamp(archive_file.stat().st_mtime)
                
                if file_mtime < cutoff_date:
                    archive_file.unlink()
                    deleted_count += 1
                    logger.debug(f"Deleted old log: {archive_file}")
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old log files")
            
            return deleted_count
        
        except Exception as e:
            logger.error(f"Failed to cleanup old logs: {e}")
            return 0
    
    async def get_log_statistics(self) -> Dict[str, any]:
        """Get statistics about log files."""
        try:
            active_logs = list(self.logs_dir.glob("**/run.log"))
            archived_logs = list(self.archive_dir.glob("*.log.gz"))
            
            total_active_size = sum(
                log.stat().st_size for log in active_logs if log.exists()
            ) / (1024 * 1024)
            
            total_archived_size = sum(
                log.stat().st_size for log in archived_logs
            ) / (1024 * 1024)
            
            return {
                "active_logs_count": len(active_logs),
                "active_logs_size_mb": round(total_active_size, 2),
                "archived_logs_count": len(archived_logs),
                "archived_logs_size_mb": round(total_archived_size, 2),
                "total_size_mb": round(total_active_size + total_archived_size, 2),
            }
        
        except Exception as e:
            logger.error(f"Failed to get log statistics: {e}")
            return {}
    
    async def compress_all_active_logs(self) -> int:
        """Compress all active logs. Returns count of compressed files."""
        compressed_count = 0
        
        try:
            for log_file in self.logs_dir.glob("**/run.log"):
                if log_file.stat().st_size > 0:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    bot_name = log_file.parent.name
                    
                    archive_name = f"{bot_name}_{timestamp}.log.gz"
                    archive_path = self.archive_dir / archive_name
                    
                    with open(log_file, 'rb') as f_in:
                        with gzip.open(archive_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    
                    log_file.write_text("")
                    compressed_count += 1
            
            logger.info(f"Compressed {compressed_count} log files")
            return compressed_count
        
        except Exception as e:
            logger.error(f"Failed to compress logs: {e}")
            return 0


# Global log manager
_log_manager = LogRotationManager()


async def rotate_logs(bot_id: int, bot_folder: str) -> bool:
    """Rotate logs for a bot."""
    return await _log_manager.rotate_bot_logs(bot_id, bot_folder)


async def cleanup_logs(max_age_days: Optional[int] = None) -> int:
    """Clean up old archived logs."""
    return await _log_manager.cleanup_old_logs(max_age_days)


async def get_log_stats() -> Dict[str, any]:
    """Get log statistics."""
    return await _log_manager.get_log_statistics()
