from __future__ import annotations

import asyncio
import logging

import uvicorn
from telegram.ext import Application
from telegram.request import HTTPXRequest

from src.bale_bot.handlers import BaleBotHandlers, register_handlers
from src.config import settings
from src.services.storage import StorageService, run_cleanup_worker
from src.services.telegram_client import TelegramBridgeService
from src.services.video_downloader import VideoDownloaderService
from src.web.server import create_web_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    storage = StorageService(
        db_path=settings.STORAGE_DB_PATH,
        download_dir=settings.DOWNLOAD_DIR,
        retention_hours=settings.FILE_RETENTION_HOURS,
    )
    await storage.initialize()

    video_service = VideoDownloaderService(
        download_dir=settings.DOWNLOAD_DIR,
        proxy_url=settings.PROXY_URL,
    )
    tg_service = TelegramBridgeService(
        api_id=settings.TG_API_ID,
        api_hash=settings.TG_API_HASH,
        session_string=settings.TG_SESSION_STRING,
        proxy_url=settings.PROXY_URL,
    )
    await tg_service.start()

    # Bale API MUST connect directly without any proxy (trust_env=False ignores HTTP_PROXY/HTTPS_PROXY)
    bale_request = HTTPXRequest(
        connection_pool_size=8,
        read_timeout=60.0,
        write_timeout=120.0,
        connect_timeout=30.0,
        httpx_kwargs={"trust_env": False},
    )
    bale_get_updates_request = HTTPXRequest(
        connection_pool_size=4,
        read_timeout=30.0,
        connect_timeout=30.0,
        httpx_kwargs={"trust_env": False},
    )

    application = (
        Application.builder()
        .token(settings.BALE_BOT_TOKEN)
        .base_url("https://tapi.bale.ai/bot")
        .base_file_url("https://tapi.bale.ai/file/bot")
        .request(bale_request)
        .get_updates_request(bale_get_updates_request)
        .build()
    )

    handlers = BaleBotHandlers(
        settings=settings,
        storage=storage,
        video_service=video_service,
        tg_service=tg_service,
    )
    register_handlers(application, handlers)

    web_app = create_web_app(storage)
    uvicorn_config = uvicorn.Config(
        web_app,
        host=settings.WEB_HOST,
        port=settings.WEB_PORT,
        log_level="info",
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    logger.info("Starting Bale Bot + FastAPI server on %s:%s", settings.WEB_HOST, settings.WEB_PORT)

    async with application:
        await application.start()
        if application.updater is None:
            raise RuntimeError("Application updater is not initialized.")
        await application.updater.start_polling(drop_pending_updates=True)

        cleanup_task = asyncio.create_task(
            run_cleanup_worker(storage, settings.CLEANUP_INTERVAL_MINUTES)
        )
        try:
            await uvicorn_server.serve()
        finally:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
            await application.updater.stop()
            await application.stop()
            await tg_service.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
