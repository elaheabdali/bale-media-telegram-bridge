from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import socks
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeAudio, Message

logger = logging.getLogger(__name__)

ChatFilterType = Literal["all", "channels", "groups"]


@dataclass(slots=True)
class TgChannel:
    channel_id: int
    title: str
    username: str | None
    kind: Literal["channel", "group"]
    unread_count: int = 0


@dataclass(slots=True)
class TgMessageItem:
    message_id: int
    date_str: str
    sender_name: str | None
    text: str
    has_media: bool
    media_badge: str | None
    file_size_mb: float | None


@dataclass(slots=True)
class TgMessagesPage:
    channel_id: int
    channel_title: str
    items: list[TgMessageItem]
    has_older: bool
    next_offset_id: int


def parse_telethon_proxy(proxy_url: str | None) -> tuple | None:
    """Convert PROXY_URL (e.g. socks5://user:pass@127.0.0.1:1080) into Telethon proxy tuple."""
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    scheme = (parsed.scheme or "").lower()
    if scheme.startswith("socks5"):
        proxy_type = socks.SOCKS5
    elif scheme.startswith("socks4"):
        proxy_type = socks.SOCKS4
    elif scheme.startswith("http"):
        proxy_type = socks.HTTP
    else:
        raise ValueError(f"Unsupported PROXY_URL scheme: {scheme}")

    if not parsed.hostname or not parsed.port:
        raise ValueError("PROXY_URL must include hostname and port.")

    if parsed.username or parsed.password:
        return (proxy_type, parsed.hostname, parsed.port, True, parsed.username, parsed.password)
    return (proxy_type, parsed.hostname, parsed.port)


def _detect_media_info(msg: Message) -> tuple[bool, str | None, float | None]:
    if not msg.media:
        return False, None, None

    if msg.photo:
        return True, "🖼 عکس", None

    doc = msg.document
    if not doc:
        return False, None, None

    size_mb = round(doc.size / (1024 * 1024), 1) if getattr(doc, "size", None) else None
    mime = getattr(doc, "mime_type", "") or ""

    if msg.video or mime.startswith("video/"):
        return True, "🎬 ویدیو", size_mb
    if msg.voice:
        return True, "🎙 ویس", size_mb
    if msg.audio or mime.startswith("audio/"):
        return True, "🎵 موزیک", size_mb

    for attr in getattr(doc, "attributes", []) or []:
        if isinstance(attr, DocumentAttributeAudio):
            return (True, "🎙 ویس" if attr.voice else "🎵 موزیک", size_mb)

    return True, "📄 فایل", size_mb


def _extract_sender_name(msg: Message) -> str | None:
    sender = getattr(msg, "sender", None)
    if not sender:
        return None
    first = getattr(sender, "first_name", None) or ""
    last = getattr(sender, "last_name", None) or ""
    full = f"{first} {last}".strip()
    if full:
        return full
    title = getattr(sender, "title", None)
    if title:
        return str(title)
    username = getattr(sender, "username", None)
    return f"@{username}" if username else None


class TelegramBridgeService:
    """Telethon MTProto wrapper for reading subscribed channels/groups and downloading media."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_string: str,
        proxy_url: str | None = None,
    ) -> None:
        proxy = parse_telethon_proxy(proxy_url)
        self.client = TelegramClient(
            StringSession(session_string),
            api_id,
            api_hash,
            proxy=proxy,
        )

    async def start(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise RuntimeError(
                "TG_SESSION_STRING is invalid or expired. Re-run scripts/generate_session.py."
            )
        me = await self.client.get_me()
        logger.info("Telethon connected as %s (id=%s)", getattr(me, "username", me.id), me.id)

    async def stop(self) -> None:
        if self.client.is_connected():
            await self.client.disconnect()

    async def get_connection_status(self) -> dict[str, object]:
        connected = self.client.is_connected()
        authorized = await self.client.is_user_authorized() if connected else False
        me = await self.client.get_me() if authorized else None
        name = None
        username = None
        if me:
            first = getattr(me, "first_name", "") or ""
            last = getattr(me, "last_name", "") or ""
            name = f"{first} {last}".strip() or str(me.id)
            username = getattr(me, "username", None)
        return {
            "connected": connected,
            "authorized": authorized,
            "name": name,
            "username": username,
        }

    async def list_dialogs(
        self,
        search_query: str | None = None,
        filter_type: ChatFilterType = "all",
    ) -> list[TgChannel]:
        items: list[TgChannel] = []
        q = search_query.strip().lower() if search_query else None

        async for dialog in self.client.iter_dialogs():
            if not (dialog.is_channel or dialog.is_group):
                continue

            entity = dialog.entity
            # In Telethon, broadcast=True means Channel; otherwise Group/Megagroup
            is_broadcast = bool(getattr(entity, "broadcast", False))
            kind: Literal["channel", "group"] = "channel" if is_broadcast else "group"

            if filter_type == "channels" and kind != "channel":
                continue
            if filter_type == "groups" and kind != "group":
                continue

            title = dialog.name or getattr(entity, "title", "بدون نام")
            username = getattr(entity, "username", None)
            if q and q not in title.lower() and (not username or q not in username.lower()):
                continue

            items.append(
                TgChannel(
                    channel_id=dialog.id,
                    title=title,
                    username=username,
                    kind=kind,
                    unread_count=dialog.unread_count or 0,
                )
            )
        return items

    async def get_channel_messages(
        self,
        channel_id: int,
        limit: int = 5,
        offset_id: int = 0,
        search_query: str | None = None,
    ) -> TgMessagesPage:
        entity = await self.client.get_entity(channel_id)
        channel_title = getattr(entity, "title", str(channel_id))
        is_group = not bool(getattr(entity, "broadcast", False))

        raw_messages: list[Message] = []
        async for msg in self.client.iter_messages(
            entity,
            limit=limit + 1,
            offset_id=offset_id,
            search=search_query or None,
        ):
            raw_messages.append(msg)

        has_older = len(raw_messages) > limit
        page_messages = raw_messages[:limit]

        items: list[TgMessageItem] = []
        for msg in page_messages:
            has_media, badge, size_mb = _detect_media_info(msg)
            date_str = msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else ""
            text = (msg.message or "").strip()
            sender_name = _extract_sender_name(msg) if is_group else None
            items.append(
                TgMessageItem(
                    message_id=msg.id,
                    date_str=date_str,
                    sender_name=sender_name,
                    text=text,
                    has_media=has_media,
                    media_badge=badge,
                    file_size_mb=size_mb,
                )
            )

        next_offset_id = page_messages[-1].id if page_messages else 0
        return TgMessagesPage(
            channel_id=channel_id,
            channel_title=channel_title,
            items=items,
            has_older=has_older,
            next_offset_id=next_offset_id,
        )

    async def download_message_media(
        self,
        channel_id: int,
        message_id: int,
        download_dir: Path,
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> tuple[Path, str]:
        download_dir.mkdir(parents=True, exist_ok=True)
        entity = await self.client.get_entity(channel_id)
        msg = await self.client.get_messages(entity, ids=message_id)
        if not msg or not msg.media:
            raise ValueError("این پیام حاوی فایل یا رسانه قابل دانلود نیست.")

        unique_prefix = uuid.uuid4().hex[:8]
        last_report = 0.0

        async def _throttled_progress(current: int, total: int) -> None:
            nonlocal last_report
            if not progress_callback or total <= 0:
                return
            now = time.monotonic()
            if now - last_report >= 3.0 or current >= total:
                last_report = now
                try:
                    await progress_callback(current, total)
                except Exception:
                    pass

        target_hint = str(download_dir / f"{unique_prefix}_")
        downloaded_path_str = await self.client.download_media(
            msg,
            file=target_hint,
            progress_callback=_throttled_progress if progress_callback else None,
        )
        if not downloaded_path_str:
            raise RuntimeError("دانلود فایل از تلگرام ناموفق بود.")

        downloaded_path = Path(downloaded_path_str)
        display_name = downloaded_path.name
        if display_name.startswith(f"{unique_prefix}_"):
            display_name = display_name[len(unique_prefix) + 1 :] or downloaded_path.name

        return downloaded_path, display_name
