from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import yt_dlp

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ChannelInfo:
    channel_id: str
    title: str
    url: str
    handle: str | None = None
    subscribers: str | None = None


@dataclass(slots=True)
class VideoSummary:
    video_id: str
    title: str
    url: str
    duration_str: str


@dataclass(slots=True)
class QualityOption:
    key: str  # e.g., "360", "480", "720", "1080", "mp3"
    label: str
    approx_size_mb: float | None = None


@dataclass(slots=True)
class VideoFormatsResult:
    video_id: str
    title: str
    url: str
    duration_str: str
    options: list[QualityOption]


@dataclass(slots=True)
class DownloadedMedia:
    file_path: Path
    title: str
    is_audio: bool


def _format_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "نامشخص"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_subscribers(count: int | float | None) -> str | None:
    if not count:
        return None
    num = float(count)
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(int(num))


class VideoDownloaderService:
    """Async wrapper around yt-dlp + ffmpeg with optional proxy routing."""

    def __init__(self, download_dir: Path, proxy_url: str | None = None) -> None:
        self.download_dir = download_dir
        self.proxy_url = proxy_url

    def _base_opts(self) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        if self.proxy_url:
            opts["proxy"] = self.proxy_url
        return opts

    async def search_channels(self, query: str, limit: int = 5) -> list[ChannelInfo]:
        return await asyncio.to_thread(self._search_channels_sync, query, limit)

    def _search_channels_sync(self, query: str, limit: int) -> list[ChannelInfo]:
        # sp=EgIQAg%3D%3D filters YouTube search results strictly to Channels
        search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=EgIQAg%253D%253D"
        opts = {
            **self._base_opts(),
            "extract_flat": True,
            "playlistend": limit * 2,
        }
        channels: list[ChannelInfo] = []
        seen_ids: set[str] = set()

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
            entries = (info or {}).get("entries") or []
            for entry in entries:
                if not entry:
                    continue
                url = entry.get("url") or entry.get("channel_url") or ""
                cid = entry.get("id") or entry.get("channel_id") or url
                title = entry.get("title") or entry.get("channel") or "بدون نام"
                if not url or cid in seen_ids:
                    continue
                seen_ids.add(cid)
                channels.append(
                    ChannelInfo(
                        channel_id=str(cid),
                        title=str(title),
                        url=str(url),
                        handle=entry.get("uploader_id"),
                        subscribers=_format_subscribers(entry.get("channel_follower_count")),
                    )
                )
                if len(channels) >= limit:
                    break

        return channels

    async def get_channel_videos(self, channel_url: str, limit: int = 8) -> list[VideoSummary]:
        return await asyncio.to_thread(self._get_channel_videos_sync, channel_url, limit)

    def _get_channel_videos_sync(self, channel_url: str, limit: int) -> list[VideoSummary]:
        target_url = channel_url.rstrip("/")
        if not target_url.endswith("/videos") and not target_url.endswith("/streams"):
            target_url = f"{target_url}/videos"

        opts = {
            **self._base_opts(),
            "extract_flat": True,
            "playlistend": limit,
        }
        videos: list[VideoSummary] = []

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target_url, download=False)
            entries = (info or {}).get("entries") or []
            for entry in entries:
                if not entry:
                    continue
                vid_id = entry.get("id") or ""
                vid_url = entry.get("url") or (
                    f"https://www.youtube.com/watch?v={vid_id}" if vid_id else ""
                )
                if not vid_url:
                    continue
                if vid_url.startswith("/") or not vid_url.startswith("http"):
                    vid_url = f"https://www.youtube.com/watch?v={vid_id}"
                videos.append(
                    VideoSummary(
                        video_id=str(vid_id),
                        title=str(entry.get("title") or "بدون عنوان"),
                        url=vid_url,
                        duration_str=_format_duration(entry.get("duration")),
                    )
                )
                if len(videos) >= limit:
                    break

        return videos

    async def get_video_formats(self, video_url: str) -> VideoFormatsResult:
        return await asyncio.to_thread(self._get_video_formats_sync, video_url)

    def _get_video_formats_sync(self, video_url: str) -> VideoFormatsResult:
        opts = {
            **self._base_opts(),
            "extract_flat": False,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                raise ValueError("اطلاعات ویدیو قابل دریافت نیست.")

        formats = info.get("formats") or []
        best_audio_size = 0
        for fmt in formats:
            if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none":
                sz = fmt.get("filesize") or fmt.get("filesize_approx") or 0
                if sz > best_audio_size:
                    best_audio_size = sz

        target_heights = [360, 480, 720, 1080]
        height_sizes: dict[int, int] = {}

        for fmt in formats:
            height = fmt.get("height")
            vcodec = fmt.get("vcodec")
            if not height or vcodec == "none":
                continue
            for target in target_heights:
                if height == target:
                    sz = fmt.get("filesize") or fmt.get("filesize_approx") or 0
                    has_audio = fmt.get("acodec") not in (None, "none")
                    total_sz = sz if (has_audio or sz == 0) else (sz + best_audio_size)
                    if target not in height_sizes or total_sz > height_sizes[target]:
                        height_sizes[target] = total_sz

        options: list[QualityOption] = []
        for h in target_heights:
            if h in height_sizes:
                mb = round(height_sizes[h] / (1024 * 1024), 1) if height_sizes[h] > 0 else None
                options.append(QualityOption(key=str(h), label=f"🎬 {h}p", approx_size_mb=mb))

        # Fallback if exact standard heights weren't reported in metadata
        if not options:
            for h in [360, 720]:
                options.append(QualityOption(key=str(h), label=f"🎬 {h}p", approx_size_mb=None))

        audio_mb = round(best_audio_size / (1024 * 1024), 1) if best_audio_size > 0 else None
        options.append(QualityOption(key="mp3", label="🎵 Audio MP3", approx_size_mb=audio_mb))

        return VideoFormatsResult(
            video_id=str(info.get("id") or ""),
            title=str(info.get("title") or "ویدیو"),
            url=str(info.get("webpage_url") or video_url),
            duration_str=_format_duration(info.get("duration")),
            options=options,
        )

    async def download_video(self, video_url: str, quality: str) -> DownloadedMedia:
        return await asyncio.to_thread(self._download_video_sync, video_url, quality)

    def _download_video_sync(self, video_url: str, quality: str) -> DownloadedMedia:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        unique_prefix = uuid.uuid4().hex[:8]
        outtmpl = str(self.download_dir / f"{unique_prefix}_%(title).80s.%(ext)s")

        is_audio = quality == "mp3"
        opts: dict[str, Any] = {
            **self._base_opts(),
            "noplaylist": True,
            "outtmpl": outtmpl,
            "restrictfilenames": True,
        }

        if is_audio:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        else:
            height = int(quality) if quality.isdigit() else 720
            opts["format"] = (
                f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={height}]+bestaudio/"
                f"best[height<={height}]/best"
            )
            opts["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            if not info:
                raise RuntimeError("دانلود ویدیو ناموفق بود.")
            prepared = Path(ydl.prepare_filename(info))

        expected_ext = ".mp3" if is_audio else ".mp4"
        final_path = prepared.with_suffix(expected_ext)
        if not final_path.is_file():
            # Fallback: find any file starting with the unique_prefix
            matches = list(self.download_dir.glob(f"{unique_prefix}_*"))
            if not matches:
                raise FileNotFoundError("فایل دانلودشده در مسیر خروجی یافت نشد.")
            final_path = matches[0]

        return DownloadedMedia(
            file_path=final_path,
            title=str(info.get("title") or final_path.stem),
            is_audio=is_audio,
        )
