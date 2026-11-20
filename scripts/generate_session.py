from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is importable when executed directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

from src.services.telegram_client import parse_telethon_proxy


def main() -> None:
    print("=== Telegram StringSession Generator ===")
    api_id_raw = input("Enter TG_API_ID: ").strip()
    api_hash = input("Enter TG_API_HASH: ").strip()
    proxy_url = input("Optional PROXY_URL (e.g. socks5://127.0.0.1:1080, or press Enter to skip): ").strip()

    if not api_id_raw.isdigit() or not api_hash:
        print("Error: Valid TG_API_ID and TG_API_HASH are required.")
        sys.exit(1)

    proxy = parse_telethon_proxy(proxy_url) if proxy_url else None

    with TelegramClient(StringSession(), int(api_id_raw), api_hash, proxy=proxy) as client:
        session_str = client.session.save()
        print("\n✅ Successfully generated TG_SESSION_STRING! Copy the line below into your .env file:\n")
        print(f"TG_SESSION_STRING={session_str}\n")


if __name__ == "__main__":
    main()
