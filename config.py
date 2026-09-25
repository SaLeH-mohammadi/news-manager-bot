import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


def _parse_int(val: str, default: int = 0) -> int:
    try:
        if "," in val:
            val = val.split(",")[0]
        return int(val.strip())
    except Exception:
        return default


@dataclass
class SettingsConfig:
    dest_channel: str = ""
    signature: str = ""
    sources: List[str] = field(default_factory=list)
    send_photo: bool = True
    send_video: bool = True
    interval_min: int = 2
    running: bool = False


@dataclass
class AppConfig:
    bot_token: str = os.getenv("BOT_TOKEN", "").strip()
    # Owner ID (safely handles commas or spaces)
    owner_id: int = _parse_int(os.getenv("OWNER_ID", os.getenv("ADMIN_ID", "0")))
    api_id: int = _parse_int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash: str = os.getenv("TELEGRAM_API_HASH", "").strip()

    supabase_url: str = os.getenv("SUPABASE_URL", "").strip()
    supabase_key: str = os.getenv("SUPABASE_KEY", "").strip()

    ninerouter_base_url: str = os.getenv("NINEROUTER_BASE_URL", "http://localhost:20128/v1").strip()
    ninerouter_api_key: str = os.getenv("NINEROUTER_API_KEY", "sk-9router").strip()
    ninerouter_model: str = os.getenv("NINEROUTER_MODEL", "gemini/gemini-3.5-flash-lite").strip()

    port: int = _parse_int(os.getenv("PORT", "8080"), default=8080)


config = AppConfig()
