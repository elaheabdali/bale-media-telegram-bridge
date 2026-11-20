# Bale Media & Telegram Bridge

A production-ready, fully `asyncio`-based **Bale Messenger Bot (بازوی بله)** integrating:
1. **YouTube Channel Search & Multi-Quality Downloader** (`yt-dlp` + `ffmpeg`).
2. **Personal Telegram Account Bridge** (`Telethon` MTProto) to browse subscribed channels, read posts, and download media.
3. **Built-in Direct Download Link Server** (`FastAPI` + `uvicorn`) running concurrently in the same event loop to serve high-speed `/dl/{token}` links.

## Key Features
- **Split Proxy Routing:** Bale Bot API (`tapi.bale.ai`) connects directly without any proxy (`trust_env=False`), while `Telethon` and `yt-dlp` optionally route through `PROXY_URL` (`socks5://` or `http://`).
- **Smart Dual Delivery:** Always provides a FastAPI direct download link; automatically uploads files `<= MAX_BALE_UPLOAD_MB` (default `45 MB`) directly to Bale chat with graceful fallback on `413 Request Entity Too Large`.
- **Strict Access Control:** Only Bale user IDs listed in `ALLOWED_BALE_USER_IDS` can interact with the bot.
- **Auto-Cleanup Worker:** Background `asyncio` worker purges expired files and SQLite tokens older than `FILE_RETENTION_HOURS` (default `6h`).

## Quick Setup

### 1. Prerequisites
- Python 3.11+
- `ffmpeg` installed on your system (or use Docker)
- A Bale Bot Token from `@BotFather` in Bale
- Telegram `TG_API_ID` & `TG_API_HASH` from [my.telegram.org](https://my.telegram.org)

### 2. Install Dependencies
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Generate Telegram StringSession (One-Time)
```bash
python scripts/generate_session.py
```
Copy the generated `TG_SESSION_STRING` output.

### 4. Configure Environment
```bash
cp .env.example .env
# Edit .env and fill in BALE_BOT_TOKEN, ALLOWED_BALE_USER_IDS, TG_API_ID, TG_API_HASH, TG_SESSION_STRING, PUBLIC_BASE_URL, and optional PROXY_URL
```

### 5. Run Locally
```bash
python -m src.main
```

### 6. Run with Docker Compose
```bash
docker compose up -d --build
```
