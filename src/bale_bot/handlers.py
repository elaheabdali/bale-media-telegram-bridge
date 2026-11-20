from __future__ import annotations

import logging
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.bale_bot.delivery import deliver_file
from src.bale_bot.keyboards import (
    back_to_home_keyboard,
    main_menu_keyboard,
    tg_channels_keyboard,
    tg_messages_keyboard,
    yt_channels_keyboard,
    yt_qualities_keyboard,
    yt_videos_keyboard,
)
from src.config import Settings
from src.services.storage import StorageService
from src.services.telegram_client import TelegramBridgeService
from src.services.video_downloader import VideoDownloaderService

logger = logging.getLogger(__name__)

ACCESS_DENIED_TEXT = "⛔ دسترسی غیرمجاز! شما اجازه استفاده از این ربات را ندارید."
WELCOME_TEXT = (
    "👋 **سلام! به ربات هوشمند مدیریت رسانه و پل تلگرام خوش آمدید.**\n\n"
    "از منوی زیر یکی از امکانات را انتخاب کنید:"
)


class BaleBotHandlers:
    """Encapsulates all Bale bot command, text, and callback query handlers."""

    def __init__(
        self,
        settings: Settings,
        storage: StorageService,
        video_service: VideoDownloaderService,
        tg_service: TelegramBridgeService,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.video_service = video_service
        self.tg_service = tg_service

    def _is_authorized(self, update: Update) -> bool:
        user = update.effective_user
        if not user:
            return False
        return user.id in self.settings.ALLOWED_BALE_USER_IDS

    async def _deny_access(self, update: Update) -> None:
        if update.callback_query:
            await update.callback_query.answer(ACCESS_DENIED_TEXT, show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(ACCESS_DENIED_TEXT)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._deny_access(update)
            return

        context.user_data.pop("state", None)
        if update.effective_message:
            await update.effective_message.reply_text(
                WELCOME_TEXT,
                reply_markup=main_menu_keyboard(),
                parse_mode="Markdown",
            )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._deny_access(update)
            return

        message = update.effective_message
        if not message or not message.text:
            return

        text = message.text.strip()
        state = context.user_data.get("state")

        if state == "awaiting_yt_channel":
            context.user_data.pop("state", None)
            status = await message.reply_text("🔍 در حال جستجوی چنل در یوتیوب...")
            try:
                channels = await self.video_service.search_channels(text, limit=5)
                if not channels:
                    await status.edit_text(
                        "❌ چنلی با این نام پیدا نشد. دوباره تلاش کنید.",
                        reply_markup=back_to_home_keyboard(),
                    )
                    return
                context.user_data["yt_channels"] = channels
                await status.edit_text(
                    f"📺 **نتایج جستجو برای `{text}`:**\nیکی از چنل‌ها را انتخاب کنید:",
                    reply_markup=yt_channels_keyboard(channels),
                    parse_mode="Markdown",
                )
            except Exception as exc:
                logger.exception("Channel search failed")
                await status.edit_text(f"❌ خطا در جستجوی چنل: {exc}")

        elif state == "awaiting_direct_url":
            context.user_data.pop("state", None)
            await self._show_video_formats(message, context, text)

        elif state == "awaiting_tg_filter":
            context.user_data.pop("state", None)
            status = await message.reply_text("🔎 در حال فیلتر کردن چنل‌های تلگرام...")
            try:
                channels = await self.tg_service.list_channels(search_query=text)
                if not channels:
                    await status.edit_text(
                        f"❌ هیچ چنلی با عبارت `{text}` یافت نشد.",
                        reply_markup=back_to_home_keyboard(),
                        parse_mode="Markdown",
                    )
                    return
                context.user_data["tg_channels"] = channels
                await status.edit_text(
                    f"📡 **چنل‌های یافت‌شده برای `{text}` ({len(channels)} مورد):**",
                    reply_markup=tg_channels_keyboard(channels, page=0),
                    parse_mode="Markdown",
                )
            except Exception as exc:
                logger.exception("Telegram channel filter failed")
                await status.edit_text(f"❌ خطا در دریافت چنل‌ها: {exc}")

        else:
            await message.reply_text(
                "لطفاً از گزینه‌های منوی اصلی استفاده کنید:",
                reply_markup=main_menu_keyboard(),
            )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            await self._deny_access(update)
            return

        query = update.callback_query
        if not query or not query.data:
            return
        await query.answer()

        data = query.data
        parts = data.split(":")

        if data == "menu:home":
            context.user_data.pop("state", None)
            await query.edit_message_text(
                WELCOME_TEXT,
                reply_markup=main_menu_keyboard(),
                parse_mode="Markdown",
            )

        elif data == "menu:yt_search":
            context.user_data["state"] = "awaiting_yt_channel"
            await query.edit_message_text(
                "🔍 **نام چنل یوتیوب مورد نظر را ارسال کنید** (مثلاً `Fireship` یا `Kurzgesagt`):",
                reply_markup=back_to_home_keyboard(),
                parse_mode="Markdown",
            )

        elif data == "menu:direct_url":
            context.user_data["state"] = "awaiting_direct_url"
            await query.edit_message_text(
                "🔗 **لینک مستقیم ویدیو را ارسال کنید:**",
                reply_markup=back_to_home_keyboard(),
                parse_mode="Markdown",
            )

        elif data == "menu:tg_channels":
            await self._load_tg_channels(query, context, page=0, refresh=True)

        elif parts[0] == "yt" and parts[1] == "ch":
            idx = int(parts[2])
            channels = context.user_data.get("yt_channels") or []
            if idx < 0 or idx >= len(channels):
                await query.edit_message_text(
                    "⚠️ اطلاعات منقضی شده است. لطفاً دوباره جستجو کنید.",
                    reply_markup=back_to_home_keyboard(),
                )
                return
            selected = channels[idx]
            await query.edit_message_text(f"⏳ در حال دریافت آخرین ویدیوهای **{selected.title}**...", parse_mode="Markdown")
            try:
                videos = await self.video_service.get_channel_videos(selected.url, limit=8)
                if not videos:
                    await query.edit_message_text(
                        "❌ ویدیویی در این چنل یافت نشد.",
                        reply_markup=back_to_home_keyboard(),
                    )
                    return
                context.user_data["yt_videos"] = videos
                await query.edit_message_text(
                    f"🎬 **آخرین ویدیوهای {selected.title}:**\nویدیوی مورد نظر را انتخاب کنید:",
                    reply_markup=yt_videos_keyboard(videos),
                    parse_mode="Markdown",
                )
            except Exception as exc:
                logger.exception("Failed fetching channel videos")
                await query.edit_message_text(f"❌ خطا در دریافت ویدیوها: {exc}", reply_markup=back_to_home_keyboard())

        elif parts[0] == "yt" and parts[1] == "vid":
            idx = int(parts[2])
            videos = context.user_data.get("yt_videos") or []
            if idx < 0 or idx >= len(videos):
                await query.edit_message_text("⚠️ اطلاعات منقضی شده است.", reply_markup=back_to_home_keyboard())
                return
            await self._show_video_formats(query.message, context, videos[idx].url, edit_message=True)

        elif parts[0] == "yt" and parts[1] == "dl":
            quality = parts[2]
            video_info: dict[str, Any] | None = context.user_data.get("yt_current_video")
            if not video_info:
                await query.edit_message_text("⚠️ لینک ویدیو یافت نشد. لطفاً دوباره انتخاب کنید.", reply_markup=back_to_home_keyboard())
                return

            await query.edit_message_text("⏳ در حال دانلود و آماده‌سازی فایل...")
            try:
                downloaded = await self.video_service.download_video(video_info["url"], quality)
                await deliver_file(
                    bot=context.bot,
                    chat_id=query.message.chat_id,
                    file_path=downloaded.file_path,
                    display_name=downloaded.file_path.name,
                    storage=self.storage,
                    settings=self.settings,
                    caption=downloaded.title,
                )
                await query.edit_message_text(
                    f"✅ دانلود و پردازش **{downloaded.title}** به پایان رسید.",
                    reply_markup=back_to_home_keyboard(),
                    parse_mode="Markdown",
                )
            except Exception as exc:
                logger.exception("Video download failed")
                await query.edit_message_text(f"❌ خطا در دانلود ویدیو: {exc}", reply_markup=back_to_home_keyboard())

        elif parts[0] == "tg" and parts[1] == "page":
            page = int(parts[2])
            await self._load_tg_channels(query, context, page=page, refresh=False)

        elif parts[0] == "tg" and parts[1] == "filter":
            context.user_data["state"] = "awaiting_tg_filter"
            await query.edit_message_text(
                "🔎 **بخشی از نام یا یوزرنیم چنل تلگرام را وارد کنید:**",
                reply_markup=back_to_home_keyboard(),
                parse_mode="Markdown",
            )

        elif parts[0] == "tg" and parts[1] == "msg":
            channel_id = int(parts[2])
            page = int(parts[3])
            await self._show_tg_messages(query, context, channel_id, page)

        elif parts[0] == "tg" and parts[1] == "dl":
            channel_id = int(parts[2])
            message_id = int(parts[3])
            await self._download_tg_media(query, context, channel_id, message_id)

    async def _show_video_formats(
        self,
        message: Any,
        context: ContextTypes.DEFAULT_TYPE,
        video_url: str,
        edit_message: bool = False,
    ) -> None:
        if edit_message:
            status = await message.edit_text("⏳ در حال بررسی کیفیت‌های موجود...")
        else:
            status = await message.reply_text("⏳ در حال بررسی کیفیت‌های موجود...")

        try:
            fmt_result = await self.video_service.get_video_formats(video_url)
            context.user_data["yt_current_video"] = {
                "url": fmt_result.url,
                "title": fmt_result.title,
            }
            text = (
                f"🎬 **{fmt_result.title}**\n"
                f"⏱ مدت زمان: `{fmt_result.duration_str}`\n\n"
                "کیفیت مورد نظر را انتخاب کنید:"
            )
            await status.edit_text(
                text,
                reply_markup=yt_qualities_keyboard(fmt_result.options),
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.exception("Failed extracting formats")
            await status.edit_text(
                f"❌ خطا در دریافت کیفیت‌های ویدیو: {exc}",
                reply_markup=back_to_home_keyboard(),
            )

    async def _load_tg_channels(
        self,
        query: Any,
        context: ContextTypes.DEFAULT_TYPE,
        page: int,
        refresh: bool,
    ) -> None:
        channels = context.user_data.get("tg_channels")
        if refresh or channels is None:
            await query.edit_message_text("⏳ در حال دریافت لیست چنل‌های تلگرام شما...")
            try:
                channels = await self.tg_service.list_channels()
                context.user_data["tg_channels"] = channels
            except Exception as exc:
                logger.exception("Failed listing Telegram channels")
                await query.edit_message_text(f"❌ خطا در ارتباط با تلگرام: {exc}", reply_markup=back_to_home_keyboard())
                return

        if not channels:
            await query.edit_message_text("📭 هیچ چنل تلگرامی یافت نشد.", reply_markup=back_to_home_keyboard())
            return

        await query.edit_message_text(
            f"📡 **چنل‌های تلگرام شما ({len(channels)} چنل):**\nصفحه {page + 1}",
            reply_markup=tg_channels_keyboard(channels, page=page),
            parse_mode="Markdown",
        )

    async def _show_tg_messages(
        self,
        query: Any,
        context: ContextTypes.DEFAULT_TYPE,
        channel_id: int,
        page: int,
    ) -> None:
        offsets_map: dict[int, list[int]] = context.user_data.setdefault("tg_offsets", {})
        offsets = offsets_map.setdefault(channel_id, [0])

        if page < 0:
            page = 0
        offset_id = offsets[page] if page < len(offsets) else offsets[-1]

        await query.edit_message_text("⏳ در حال دریافت پیام‌های چنل...")
        try:
            msg_page = await self.tg_service.get_channel_messages(
                channel_id=channel_id,
                limit=5,
                offset_id=offset_id,
            )
        except Exception as exc:
            logger.exception("Failed reading channel messages")
            await query.edit_message_text(f"❌ خطا در خواندن پیام‌ها: {exc}", reply_markup=back_to_home_keyboard())
            return

        if msg_page.has_older and len(offsets) <= page + 1:
            offsets.append(msg_page.next_offset_id)

        if not msg_page.items:
            await query.edit_message_text(
                "📭 پیامی در این صفحه یافت نشد.",
                reply_markup=tg_messages_keyboard(channel_id, [], page, has_older=False),
            )
            return

        lines: list[str] = [f"📢 **{msg_page.channel_title}** (صفحه {page + 1})\n"]
        for item in msg_page.items:
            badge = f" | {item.media_badge}" if item.media_badge else ""
            snippet = item.text[:450] + ("..." if len(item.text) > 450 else "")
            if not snippet:
                snippet = "_(بدون متن)_"
            lines.append(f"🔹 **#{item.message_id}** | 🕒 `{item.date_str}`{badge}\n{snippet}\n")

        full_text = "\n".join(lines)
        if len(full_text) > 3800:
            full_text = full_text[:3800] + "\n\n... _(ادامه متن به دلیل محدودیت طول پیام کوتاه شد)_"

        await query.edit_message_text(
            full_text,
            reply_markup=tg_messages_keyboard(channel_id, msg_page.items, page, msg_page.has_older),
            parse_mode="Markdown",
        )

    async def _download_tg_media(
        self,
        query: Any,
        context: ContextTypes.DEFAULT_TYPE,
        channel_id: int,
        message_id: int,
    ) -> None:
        status_msg = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"⏳ در حال شروع دانلود پست `#{message_id}` از تلگرام...",
            parse_mode="Markdown",
        )

        async def _progress(current: int, total: int) -> None:
            pct = (current / total) * 100
            cur_mb = current / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            await status_msg.edit_text(
                f"⏳ در حال دانلود پست `#{message_id}`...\n📊 پیشرفت: `{pct:.0f}%` ({cur_mb:.1f} / {tot_mb:.1f} MB)",
                parse_mode="Markdown",
            )

        try:
            file_path, display_name = await self.tg_service.download_message_media(
                channel_id=channel_id,
                message_id=message_id,
                download_dir=self.settings.DOWNLOAD_DIR,
                progress_callback=_progress,
            )
            await status_msg.edit_text("📤 دانلود از تلگرام کامل شد. در حال آماده‌سازی لینک و ارسال...")
            await deliver_file(
                bot=context.bot,
                chat_id=query.message.chat_id,
                file_path=file_path,
                display_name=display_name,
                storage=self.storage,
                settings=self.settings,
                caption=f"پست #{message_id}",
            )
            await status_msg.delete()
        except Exception as exc:
            logger.exception("Telegram media download failed")
            await status_msg.edit_text(f"❌ خطا در دانلود رسانه تلگرام: {exc}")


def register_handlers(application: Application, handlers: BaleBotHandlers) -> None:
    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CallbackQueryHandler(handlers.handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_text))
