"""
Bot export and update utilities for improved bot management.
Implements features from TODO.md: export as ZIP, update without delete, clone.
"""

from __future__ import annotations

import zipfile
import shutil
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from datetime import datetime

from database import get_bot, get_env_vars, set_env_var, insert_bot
from config import config

logger = logging.getLogger(__name__)


async def export_bot_zip(bot_id: int, output_path: Optional[Path] = None) -> Path:
    """
    Export bot as ZIP file for backup or transfer.
    
    Args:
        bot_id: ID of bot to export
        output_path: Optional custom output path
    
    Returns:
        Path to created ZIP file
    
    Raises:
        ValueError: If bot not found
    """
    bot = await get_bot(bot_id)
    if not bot:
        raise ValueError(f"Bot {bot_id} not found")
    
    bot_folder = Path(config.BOTS_DIR) / bot.folder
    if not bot_folder.exists():
        raise ValueError(f"Bot folder not found: {bot_folder}")
    
    # Generate output path
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(config.BACKUP_DIR) / f"{bot.name}_{bot_id}_{timestamp}.zip"
    
    # Create ZIP file
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in bot_folder.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(bot_folder)
                zf.write(file_path, arcname)
                logger.debug(f"Added {arcname} to ZIP")
    
    logger.info(f"Bot {bot_id} exported to {output_path}")
    return output_path


async def update_bot_code(
    bot_id: int,
    new_zip_path: Path,
    preserve_env: bool = True,
) -> bool:
    """
    Update bot code without deleting and recreating it.
    Preserves owner_id, settings, and optionally environment variables.
    
    Args:
        bot_id: ID of bot to update
        new_zip_path: Path to new ZIP file
        preserve_env: Whether to preserve existing env vars
    
    Returns:
        True if update successful
    
    Raises:
        ValueError: If bot or ZIP not found
    """
    bot = await get_bot(bot_id)
    if not bot:
        raise ValueError(f"Bot {bot_id} not found")
    
    if not new_zip_path.exists():
        raise ValueError(f"ZIP file not found: {new_zip_path}")
    
    # Backup current bot folder
    bot_folder = Path(config.BOTS_DIR) / bot.folder
    backup_folder = bot_folder.with_name(f"{bot_folder.name}_backup")
    
    try:
        # Backup current version
        if bot_folder.exists():
            shutil.copytree(bot_folder, backup_folder)
            logger.info(f"Backed up bot {bot_id} to {backup_folder}")
        
        # Clear bot folder
        if bot_folder.exists():
            shutil.rmtree(bot_folder)
        
        bot_folder.mkdir(parents=True, exist_ok=True)
        
        # Extract new code
        with zipfile.ZipFile(new_zip_path, 'r') as zf:
            zf.extractall(bot_folder)
        
        logger.info(f"Updated bot {bot_id} code from {new_zip_path}")
        
        # Clean backup if successful
        if backup_folder.exists():
            shutil.rmtree(backup_folder)
        
        return True
    
    except Exception as e:
        logger.error(f"Failed to update bot {bot_id}: {e}")
        
        # Restore backup
        if backup_folder.exists():
            if bot_folder.exists():
                shutil.rmtree(bot_folder)
            shutil.move(backup_folder, bot_folder)
            logger.info(f"Restored bot {bot_id} from backup")
        
        raise


async def clone_bot(
    source_bot_id: int,
    new_owner_id: int,
    new_bot_name: str,
    copy_env: bool = True,
) -> int:
    """
    Clone a bot for another user.
    Copies code, settings, and optionally environment variables.
    
    Args:
        source_bot_id: ID of bot to clone
        new_owner_id: ID of new owner
        new_bot_name: Name for cloned bot
        copy_env: Whether to copy env vars
    
    Returns:
        ID of cloned bot
    
    Raises:
        ValueError: If source bot not found
    """
    source_bot = await get_bot(source_bot_id)
    if not source_bot:
        raise ValueError(f"Source bot {source_bot_id} not found")
    
    # Create new bot entry
    new_bot = await insert_bot(
        owner_id=new_owner_id,
        name=new_bot_name,
        folder="",
        entry_file=source_bot.entry_file,
        max_memory_mb=source_bot.max_memory_mb,
    )
    
    try:
        # Copy bot files
        source_folder = Path(config.BOTS_DIR) / source_bot.folder
        new_folder = Path(config.BOTS_DIR) / f"bot_{new_bot.id}"
        
        if source_folder.exists():
            shutil.copytree(source_folder, new_folder)
            new_bot.folder = f"bot_{new_bot.id}"
        
        # Copy environment variables if requested
        if copy_env:
            source_env = await get_env_vars(source_bot_id)
            for key, value in source_env.items():
                await set_env_var(new_bot.id, key, value)
            logger.info(f"Copied {len(source_env)} env vars to bot {new_bot.id}")
        
        logger.info(
            f"Cloned bot {source_bot_id} to {new_bot.id} "
            f"for user {new_owner_id}"
        )
        
        return new_bot.id
    
    except Exception as e:
        logger.error(f"Failed to clone bot {source_bot_id}: {e}")
        # Delete incomplete bot
        from database import delete_bot
        await delete_bot(new_bot.id)
        raise


async def get_bot_update_history(
    bot_id: int,
    limit: int = 10,
) -> list[Dict[str, Any]]:
    """
    Get history of bot updates from backup records.
    
    Args:
        bot_id: ID of bot
        limit: Maximum number of records
    
    Returns:
        List of update history records
    """
    from database import get_backup_records
    
    all_backups = await get_backup_records(limit=limit * 2)
    
    # Filter for this bot and sort by date
    bot_backups = [
        {
            "id": b.id,
            "backup_type": b.backup_type,
            "status": b.status,
            "file_size_mb": b.file_size_mb,
            "created_at": b.created_at.isoformat(),
        }
        for b in all_backups
        if b.file_path and str(bot_id) in b.file_path
    ][:limit]
    
    return bot_backups
