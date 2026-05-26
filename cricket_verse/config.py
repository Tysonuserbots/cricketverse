from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    gemini_api_key: str | None
    gemini_model: str
    database_path: str
    run_mode: str
    port: int
    webhook_path: str
    webhook_url: str | None


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env or your environment.")

    return Settings(
        telegram_bot_token=token,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip(),
        database_path=os.getenv("DATABASE_PATH", "cricket_verse.sqlite3").strip(),
        run_mode=os.getenv("RUN_MODE", "polling").strip().lower(),
        port=int(os.getenv("PORT", "10000")),
        webhook_path=os.getenv("WEBHOOK_PATH", "telegram-webhook").strip().strip("/"),
        webhook_url=os.getenv("WEBHOOK_URL", "").strip() or None,
    )
