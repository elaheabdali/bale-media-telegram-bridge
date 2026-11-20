from __future__ import annotations

import logging
from pathlib import Path

from telegram import Bot
from telegram.error import BadRequest, NetworkError, TelegramError

from src.config import Settings
from src.services.storage import StorageService

logger = logging.getLogger(__name__)


async def deliver_file(
    bot: Bot,
    chat_id: int,
    file_path: Path,
    display_name: str,
    storage: StorageService,
    settings: Settings,
    caption: str | None = None,
) -> None:
    """
    Smart Dual Delivery:
    1. Always register the file and send a high-speed Direct Download Link.
    2. If size <= MAX_BALE_UPLOAD_MB, also upload the media directly to Bale.
       Gracefully handles 413 Request Entity Too Large errors.
    """
    stored = await storage.register_file(file_path, display_name=display_name)
    download_url = f"{settings.PUBLIC_BASE_URL}/dl/{stored.token}"
    size_mb = stored.file_size / (1024 * 1024)

    header = f"✅ **فایل آماده شد!**\n📄 نام فایل: `{stored.filename}`\n📦 حجم: `{size_mb:.1f} MB`"
    if caption:
        header = f"{header}\n📝 {caption}"

    link_message = (
        f"{header}\n\n"
        f"🔗 **لینک دانلود مستقیم (معتبر تا {settings.FILE_RETENTION_HOURS} ساعت):**\n"
        f"{download_url}"
    )

    await bot.send_message(chat_id=chat_id, text=link_message, parse_mode="Markdown")

    if stored.file_size > settings.max_bale_upload_bytes:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"ℹ️ به دلیل محدودیت حجم آپلود در پیام‌رسان بله (حداکثر {settings.MAX_BALE_UPLOAD_MB} مگابایت)، "
                "فایل به صورت مستقیم ارسال نشد و تنها لینک دانلود مستقیم با سرعت بالا در اختیار شما قرار گرفت."
            ),
        )
        return

    try:
        mime = stored.mime_type.lower()
        with stored.file_path.open("rb") as f:
            if mime.startswith("video/"):
                await bot.send_video(
                    chat_id=chat_id,
                    video=f,
                    filename=stored.filename,
                    caption=stored.filename,
                    read_timeout=120,
                    write_timeout=120,
                )
            elif mime.startswith("audio/"):
                await bot.send_audio(
                    chat_id=chat_id,
                    audio=f,
                    filename=stored.filename,
                    title=stored.filename,
                    read_timeout=120,
                    write_timeout=120,
                )
            elif mime.startswith("image/"):
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=stored.filename,
                    read_timeout=120,
                    write_timeout=120,
                )
            else:
                await bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=stored.filename,
                    caption=stored.filename,
                    read_timeout=120,
                    write_timeout=120,
                )
    except (BadRequest, NetworkError, TelegramError) as exc:
        err_text = str(exc).lower()
        logger.warning("Failed to upload file %s to Bale: %s", stored.filename, exc)
        if "413" in err_text or "too large" in err_text or "entity" in err_text:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ سرور بله فایل را به دلیل محدودیت حجم (413 Request Entity Too Large) نپذیرفت. "
                    "لطفاً از لینک دانلود مستقیم در پیام بالا استفاده کنید."
                ),
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ در آپلود مستقیم فایل در بله خطایی رخ داد، اما لینک دانلود مستقیم بالا فعال و آماده است."
                ),
            )
