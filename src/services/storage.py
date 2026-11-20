from __future__ import annotations

import asyncio
import logging
import mimetypes
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StoredFile:
    token: str
    file_path: Path
    filename: str
    mime_type: str
    file_size: int
    created_at: float


class StorageService:
    """Manages direct download tokens, SQLite metadata persistence, and auto-cleanup."""

    def __init__(self, db_path: Path, download_dir: Path, retention_hours: int) -> None:
        self.db_path = db_path
        self.download_dir = download_dir
        self.retention_seconds = retention_hours * 3600

    async def initialize(self) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS download_tokens (
                    token TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_created_at ON download_tokens(created_at)"
            )
            await db.commit()

    async def register_file(self, file_path: Path, display_name: str | None = None) -> StoredFile:
        resolved = file_path.resolve()
        filename = display_name or resolved.name
        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = "application/octet-stream"
        file_size = resolved.stat().st_size
        token = secrets.token_urlsafe(24)
        created_at = time.time()

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO download_tokens (token, file_path, filename, mime_type, file_size, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token, str(resolved), filename, mime_type, file_size, created_at),
            )
            await db.commit()

        return StoredFile(
            token=token,
            file_path=resolved,
            filename=filename,
            mime_type=mime_type,
            file_size=file_size,
            created_at=created_at,
        )

    async def get_file(self, token: str) -> StoredFile | None:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """
                SELECT token, file_path, filename, mime_type, file_size, created_at
                FROM download_tokens
                WHERE token = ?
                """,
                (token,),
            ) as cursor:
                row = await cursor.fetchone()

        if not row:
            return None

        stored = StoredFile(
            token=row[0],
            file_path=Path(row[1]),
            filename=row[2],
            mime_type=row[3],
            file_size=row[4],
            created_at=row[5],
        )

        if time.time() - stored.created_at > self.retention_seconds:
            await self.delete_token(token, delete_disk_file=True)
            return None

        if not stored.file_path.is_file():
            await self.delete_token(token, delete_disk_file=False)
            return None

        return stored

    async def delete_token(self, token: str, delete_disk_file: bool = True) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            if delete_disk_file:
                async with db.execute(
                    "SELECT file_path FROM download_tokens WHERE token = ?", (token,)
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    Path(row[0]).unlink(missing_ok=True)

            await db.execute("DELETE FROM download_tokens WHERE token = ?", (token,))
            await db.commit()

    async def cleanup_expired(self, force_all: bool = False) -> int:
        cutoff = time.time() + 1 if force_all else (time.time() - self.retention_seconds)
        deleted_count = 0

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT token, file_path FROM download_tokens WHERE created_at < ?",
                (cutoff,),
            ) as cursor:
                expired_rows = await cursor.fetchall()

            for token, raw_path in expired_rows:
                try:
                    Path(raw_path).unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Failed to remove expired file %s: %s", raw_path, exc)
                await db.execute("DELETE FROM download_tokens WHERE token = ?", (token,))
                deleted_count += 1

            await db.commit()

        # Also clean orphan files in downloads/
        for path in self.download_dir.iterdir():
            if path.name in {".gitkeep", self.db_path.name} or path.name.startswith("storage.db"):
                continue
            try:
                if path.is_file() and (
                    force_all or (time.time() - path.stat().st_mtime) > self.retention_seconds
                ):
                    path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Failed to remove orphan file %s: %s", path, exc)

        if deleted_count:
            logger.info("Cleanup removed %d download entries.", deleted_count)
        return deleted_count


async def run_cleanup_worker(storage: StorageService, interval_minutes: int) -> None:
    """Periodic background task that purges expired files and tokens."""
    interval_seconds = max(60, interval_minutes * 60)
    while True:
        try:
            await storage.cleanup_expired()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in storage cleanup worker")
        await asyncio.sleep(interval_seconds)
