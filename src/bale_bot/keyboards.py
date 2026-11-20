from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.services.telegram_client import ChatFilterType, TgChannel, TgMessageItem
from src.services.video_downloader import ChannelInfo, QualityOption, VideoSummary


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📡 چنل‌ها و گروه‌های تلگرام من", callback_data="menu:tg_channels")],
            [InlineKeyboardButton("🔍 جستجوی چنل ویدیویی (یوتیوب)", callback_data="menu:yt_search")],
            [InlineKeyboardButton("🔗 دانلود مستقیم با لینک", callback_data="menu:direct_url")],
            [InlineKeyboardButton("📊 وضعیت اتصال و حافظه", callback_data="menu:status")],
        ]
    )


def back_to_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="menu:home")]]
    )


def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔄 بررسی مجدد وضعیت", callback_data="menu:status")],
            [InlineKeyboardButton("🧹 پاکسازی فایل‌های موقت", callback_data="sys:cleanup")],
            [InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="menu:home")],
        ]
    )


def yt_channels_keyboard(channels: list[ChannelInfo]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, ch in enumerate(channels):
        sub = f" ({ch.subscribers})" if ch.subscribers else ""
        handle = f" [{ch.handle}]" if ch.handle else ""
        label = f"📺 {ch.title[:35]}{handle}{sub}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"yt:ch:{idx}")])
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def yt_videos_keyboard(videos: list[VideoSummary]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, vid in enumerate(videos, start=1):
        label = f"{idx}. {vid.title[:38]} ({vid.duration_str})"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"yt:vid:{idx - 1}")])
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def yt_qualities_keyboard(options: list[QualityOption]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for opt in options:
        size_part = f" (~{opt.approx_size_mb} MB)" if opt.approx_size_mb else ""
        btn = InlineKeyboardButton(f"{opt.label}{size_part}", callback_data=f"yt:dl:{opt.key}")
        current_row.append(btn)
        if len(current_row) == 2:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:home")])
    return InlineKeyboardMarkup(rows)


def tg_channels_keyboard(
    channels: list[TgChannel],
    page: int,
    filter_type: ChatFilterType = "all",
    per_page: int = 8,
) -> InlineKeyboardMarkup:
    total = len(channels)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    chunk = channels[start : start + per_page]

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                "✅ همه" if filter_type == "all" else "🗂 همه",
                callback_data="tg:type:all",
            ),
            InlineKeyboardButton(
                "✅ چنل‌ها" if filter_type == "channels" else "📢 چنل‌ها",
                callback_data="tg:type:channels",
            ),
            InlineKeyboardButton(
                "✅ گروه‌ها" if filter_type == "groups" else "👥 گروه‌ها",
                callback_data="tg:type:groups",
            ),
        ]
    ]

    for ch in chunk:
        icon = "📢" if ch.kind == "channel" else "👥"
        unread = f" ({ch.unread_count} جدید)" if ch.unread_count > 0 else ""
        label = f"{icon} {ch.title[:36]}{unread}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"tg:msg:{ch.channel_id}:0")])

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"tg:page:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("➡️ بعدی", callback_data=f"tg:page:{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton("🔎 جستجوی نام", callback_data="tg:filter"),
            InlineKeyboardButton("🔄 بروزرسانی", callback_data="menu:tg_channels"),
            InlineKeyboardButton("🏠 منو", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def tg_messages_keyboard(
    channel_id: int,
    items: list[TgMessageItem],
    page: int,
    has_older: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for item in items:
        if item.has_media:
            size_txt = f" ({item.file_size_mb} MB)" if item.file_size_mb else ""
            btn_text = f"📥 دانلود محتوای پست #{item.message_id}{size_txt}"
            rows.append(
                [
                    InlineKeyboardButton(
                        btn_text[:60],
                        callback_data=f"tg:dl:{channel_id}:{item.message_id}",
                    )
                ]
            )

    nav_row: list[InlineKeyboardButton] = []
    if has_older:
        nav_row.append(
            InlineKeyboardButton(
                "پیام‌های قدیمی‌تر ⬅️",
                callback_data=f"tg:msg:{channel_id}:{page + 1}",
            )
        )
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                "پیام‌های جدیدتر ➡️",
                callback_data=f"tg:msg:{channel_id}:{page - 1}",
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton("🔄 بروزرسانی چت", callback_data=f"tg:msg:{channel_id}:0"),
            InlineKeyboardButton("🔎 جستجو در چت", callback_data=f"tg:search:{channel_id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("📡 بازگشت به لیست چنل‌ها و گروه‌ها", callback_data="tg:page:0"),
            InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(rows)
