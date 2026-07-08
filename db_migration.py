#!/usr/bin/env python3
"""
Database migration script for Burrq v1.0.0
Creates and updates SQLite tables for download history and analytics.
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

HISTORY_DB_PATH = Path(__file__).parent / "history.db"


def run_migrations():
    """Run all database migrations for download_history and analytics_logs tables."""
    with sqlite3.connect(HISTORY_DB_PATH) as conn:
        # Create download_history table with all required columns
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                filepath TEXT,
                size_bytes INTEGER DEFAULT 0,
                completed_at TEXT NOT NULL,
                file_type TEXT DEFAULT 'video',
                status TEXT DEFAULT 'completed'
            )
            """
        )
        
        # Create analytics_logs table (Phase 3)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                file_format TEXT NOT NULL,
                is_playlist_item INTEGER DEFAULT 0,
                target_folder_path TEXT
            )
            """
        )
        
        # Create indexes for performance
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_history_completed_at ON download_history(completed_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_history_title ON download_history(title)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_history_file_type ON download_history(file_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_download_history_status ON download_history(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_timestamp ON analytics_logs(timestamp DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_format ON analytics_logs(file_format)"
        )
        
        # Migration: Add missing columns to existing table
        _migrate_history_table(conn)
        
        conn.commit()
        logger.info("Database migrations completed successfully")


def _migrate_history_table(conn) -> None:
    """Migrate existing history table to add missing columns."""
    try:
        # Check if file_type column exists
        cursor = conn.execute("PRAGMA table_info(download_history)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # Add file_type column if missing
        if 'file_type' not in columns:
            conn.execute("ALTER TABLE download_history ADD COLUMN file_type TEXT DEFAULT 'video'")
            logger.info("Migrated history table: added file_type column")
        
        # Add status column if missing
        if 'status' not in columns:
            conn.execute("ALTER TABLE download_history ADD COLUMN status TEXT DEFAULT 'completed'")
            logger.info("Migrated history table: added status column")
    except Exception as exc:
        logger.debug("Could not migrate history table: %s", exc)


if __name__ == "__main__":
    run_migrations()