from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bale Bot
    BALE_BOT_TOKEN: str
    ALLOWED_BALE_USER_IDS: Annotated[list[int], NoDecode] = Field(default_factory=list)

    # Telegram MTProto (Telethon)
    TG_API_ID: int
    TG_API_HASH: str
    TG_SESSION_STRING: str

    # Optional Proxy (Used ONLY for Telethon and yt-dlp, NEVER for Bale API)
    PROXY_URL: str | None = None

    # Direct Link Web Server
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    WEB_HOST: str = "0.0.0.0"
    WEB_PORT: int = 8000

    # Storage & Delivery Limits
    DOWNLOAD_DIR: Path = Path("downloads")
    STORAGE_DB_PATH: Path = Path("downloads/storage.db")
    MAX_BALE_UPLOAD_MB: int = 45
    FILE_RETENTION_HOURS: int = 6
    CLEANUP_INTERVAL_MINUTES: int = 30

    @field_validator("ALLOWED_BALE_USER_IDS", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, value: object) -> list[int]:
        if isinstance(value, list):
            return [int(v) for v in value]
        if isinstance(value, int):
            return [value]
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return []

    @field_validator("PROXY_URL", mode="before")
    @classmethod
    def normalize_proxy_url(cls, value: object) -> str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value if isinstance(value, str) else None

    @field_validator("PUBLIC_BASE_URL", mode="before")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def max_bale_upload_bytes(self) -> int:
        return self.MAX_BALE_UPLOAD_MB * 1024 * 1024


settings = Settings()
