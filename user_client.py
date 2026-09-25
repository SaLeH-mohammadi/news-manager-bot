import asyncio
import io
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
import qrcode
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from config import config
from database import db

logger = logging.getLogger(__name__)

MEDIA_DIR = "/tmp/news_bot_media"
os.makedirs(MEDIA_DIR, exist_ok=True)


def normalize_channel_target(entity_str: str):
    target = entity_str.strip()
    for prefix in ["https://t.me/joinchat/", "https://t.me/+", "https://t.me/", "t.me/"]:
        if target.startswith(prefix):
            target = target.replace(prefix, "")
            break

    if target.startswith("-100") and target[4:].isdigit():
        return int(target)
    elif target.startswith("-") and target[1:].isdigit():
        return int(target)
    elif target.isdigit():
        return int(target)
    elif not target.startswith("@") and not target.startswith("+"):
        return f"@{target}"
    return target


class UserClientManager:
    def __init__(self):
        self.clients: Dict[int, TelegramClient] = {}
        self._active_qr_logins: Dict[int, Any] = {}
        self._pending_2fa: Dict[int, bool] = {}

    async def get_or_create_client(self, user_id: int) -> TelegramClient:
        if user_id in self.clients:
            client = self.clients[user_id]
            if not client.is_connected():
                try:
                    await client.connect()
                except Exception as e:
                    logger.warning(f"Reconnecting client for {user_id}: {e}")
            if await client.is_user_authorized():
                return client

        # Load session string from persistent local storage or Supabase
        session_str = await db.get_kv(f"telethon_session_{user_id}", default="")
        if not session_str and user_id != config.owner_id:
            session_str = await db.get_kv("telethon_session", default="")

        session = StringSession(session_str if session_str else "")

        client = TelegramClient(
            session,
            config.api_id,
            config.api_hash,
            device_model=f"NewsBot_{user_id}",
            app_version="2.0",
        )
        await client.connect()
        self.clients[user_id] = client
        return client

    async def is_authorized(self, user_id: int) -> bool:
        try:
            client = await self.get_or_create_client(user_id)
            return await client.is_user_authorized()
        except Exception as e:
            logger.error(f"Error checking user authorization for {user_id}: {e}")
            return False

    async def get_me(self, user_id: int) -> Optional[Any]:
        try:
            client = await self.get_or_create_client(user_id)
            if await client.is_user_authorized():
                return await client.get_me()
        except Exception as e:
            logger.error(f"Error getting user info for {user_id}: {e}")
        return None

    def generate_qr_image(self, url: str) -> io.BytesIO:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    async def start_qr_login(
        self,
        user_id: int,
        on_qr_generated: Callable[[io.BytesIO], Any],
        on_success: Callable[[Any], Any],
        on_2fa_needed: Callable[[], Any],
        on_timeout: Callable[[], Any],
        on_error: Callable[[str], Any],
    ):
        self._pending_2fa[user_id] = False

        try:
            client = TelegramClient(
                StringSession(""),
                config.api_id,
                config.api_hash,
                device_model=f"NewsBot_{user_id}",
                app_version="2.0",
            )
            await client.connect()

            qr_login_obj = await client.qr_login()
            self._active_qr_logins[user_id] = (client, qr_login_obj)

            qr_bytes = self.generate_qr_image(qr_login_obj.url)
            await on_qr_generated(qr_bytes)

            try:
                user = await qr_login_obj.wait(timeout=120)
                session_str = client.session.save()
                await db.set_kv(f"telethon_session_{user_id}", session_str)
                self.clients[user_id] = client
                await on_success(user)
            except errors.SessionPasswordNeededError:
                self._pending_2fa[user_id] = True
                await on_2fa_needed()
            except asyncio.TimeoutError:
                await on_timeout()

        except Exception as e:
            logger.error(f"QR login exception for {user_id}: {e}")
            await on_error(str(e))

    async def submit_2fa_password(self, user_id: int, password: str) -> Tuple[bool, str]:
        if not self._pending_2fa.get(user_id) or user_id not in self._active_qr_logins:
            return False, "هیچ درخواستی در انتظار رمز دو مرحله‌ای نیست."

        client, _ = self._active_qr_logins[user_id]
        try:
            user = await client.sign_in(password=password)
            session_str = client.session.save()
            await db.set_kv(f"telethon_session_{user_id}", session_str)
            self.clients[user_id] = client
            self._pending_2fa[user_id] = False
            return True, f"ورود با موفقیت انجام شد: {getattr(user, 'first_name', 'User')}"
        except errors.PasswordHashInvalidError:
            return False, "رمز دو مرحله‌ای وارد شده نادرست است."
        except Exception as e:
            logger.error(f"Error submitting 2FA for {user_id}: {e}")
            return False, f"خطا در ورود: {str(e)}"

    async def fetch_channel_messages(self, user_id: int, entity_str: str, limit: int = 10) -> List[Any]:
        client = await self.get_or_create_client(user_id)
        if not await client.is_user_authorized():
            return []

        try:
            target = normalize_channel_target(entity_str)
            return await client.get_messages(target, limit=limit)
        except Exception as e:
            logger.error(f"Failed to fetch messages for user {user_id} from {entity_str}: {e}")
            return []

    async def download_media(
        self, user_id: int, message: Any, allow_photo: bool, allow_video: bool
    ) -> Tuple[Optional[str], Optional[str]]:
        if not message.media:
            return None, None

        media_type = None
        if isinstance(message.media, MessageMediaPhoto) and allow_photo:
            media_type = "photo"
        elif isinstance(message.media, MessageMediaDocument) and allow_video:
            if hasattr(message.media, "document") and message.media.document.mime_type.startswith("video"):
                media_type = "video"

        if not media_type:
            return None, None

        client = await self.get_or_create_client(user_id)
        try:
            filename = f"msg_{user_id}_{message.chat_id}_{message.id}"
            dest = os.path.join(MEDIA_DIR, filename)
            downloaded_path = await client.download_media(message, file=dest)
            return media_type, downloaded_path
        except Exception as e:
            logger.error(f"Error downloading media for user {user_id} msg {message.id}: {e}")
            return None, None


user_client_manager = UserClientManager()
