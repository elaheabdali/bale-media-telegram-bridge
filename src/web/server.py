from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from src.services.storage import StorageService


def create_web_app(storage: StorageService) -> FastAPI:
    """Create the FastAPI application serving direct download links."""
    app = FastAPI(title="Bale Media Direct Download Server", docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/dl/{token}")
    async def download_file(token: str) -> FileResponse:
        stored = await storage.get_file(token)
        if not stored:
            raise HTTPException(status_code=404, detail="Download link expired or not found.")

        return FileResponse(
            path=stored.file_path,
            filename=stored.filename,
            media_type=stored.mime_type,
        )

    return app
