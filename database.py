import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
from dataclasses import asdict
from supabase import create_client, Client
from config import config, SettingsConfig

logger = logging.getLogger(__name__)


def with_retry(max_retries: int = 3, delay: float = 1.0):
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    logger.warning(f"DB call '{func.__name__}' failed (attempt {attempt}/{max_retries}): {e}")
                    if attempt < max_retries:
                        time.sleep(delay * attempt)
            logger.error(f"DB call '{func.__name__}' permanently failed: {last_err}")
            raise last_err
        return wrapper
    return decorator


class Database:
    def __init__(self):
        self.client: Optional[Client] = None
        if config.supabase_url and config.supabase_key:
            try:
                self.client = create_client(config.supabase_url, config.supabase_key)
                logger.info("Supabase client initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
        else:
            logger.warning("SUPABASE_URL or SUPABASE_KEY missing.")

    @with_retry(max_retries=3, delay=1.0)
    def _sync_get_kv(self, key: str) -> Optional[Any]:
        if not self.client:
            return None
        res = self.client.table("nm_kv").select("value").eq("key", key).limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0].get("value")
        return None

    async def get_kv(self, key: str, default: Any = None) -> Any:
        try:
            val = await asyncio.to_thread(self._sync_get_kv, key)
            return val if val is not None else default
        except Exception as e:
            logger.error(f"Error reading KV key '{key}': {e}")
            return default

    @with_retry(max_retries=3, delay=1.0)
    def _sync_set_kv(self, key: str, value: Any) -> bool:
        if not self.client:
            return False
        self.client.table("nm_kv").upsert({"key": key, "value": value}).execute()
        return True

    async def set_kv(self, key: str, value: Any) -> bool:
        try:
            return await asyncio.to_thread(self._sync_set_kv, key, value)
        except Exception as e:
            logger.error(f"Error saving KV key '{key}': {e}")
            return False

    # --- User Access Whitelist ---
    async def get_authorized_users(self) -> List[int]:
        users = await self.get_kv("authorized_users", default=[])
        if not isinstance(users, list):
            users = []
        if config.owner_id and config.owner_id not in users:
            users.append(config.owner_id)
        return [int(u) for u in users]

    async def add_authorized_user(self, user_id: int) -> bool:
        users = await self.get_authorized_users()
        if user_id not in users:
            users.append(user_id)
            return await self.set_kv("authorized_users", users)
        return True

    async def remove_authorized_user(self, user_id: int) -> bool:
        if user_id == config.owner_id:
            return False  # Cannot remove owner
        users = await self.get_authorized_users()
        if user_id in users:
            users.remove(user_id)
            return await self.set_kv("authorized_users", users)
        return True

    async def is_user_authorized(self, user_id: int) -> bool:
        if user_id == config.owner_id:
            return True
        users = await self.get_authorized_users()
        return user_id in users

    # --- Per-User Isolated Settings ---
    async def get_user_settings(self, user_id: int) -> SettingsConfig:
        key = f"settings_{user_id}"
        stored = await self.get_kv(key, default=None)
        if not stored or not isinstance(stored, dict):
            # Clean empty settings for new user
            init_settings = SettingsConfig()
            await self.save_user_settings(user_id, init_settings)
            return init_settings

        return SettingsConfig(
            dest_channel=stored.get("dest_channel", ""),
            signature=stored.get("signature", ""),
            sources=stored.get("sources", []),
            send_photo=stored.get("send_photo", True),
            send_video=stored.get("send_video", True),
            interval_min=stored.get("interval_min", 2),
            running=stored.get("running", False),
        )

    async def save_user_settings(self, user_id: int, settings: SettingsConfig) -> bool:
        key = f"settings_{user_id}"
        return await self.set_kv(key, asdict(settings))

    async def get_all_running_users(self) -> List[int]:
        users = await self.get_authorized_users()
        running_users = []
        for u in users:
            st = await self.get_user_settings(u)
            if st.running:
                running_users.append(u)
        return running_users

    # --- Per-User Hash Deduplication ---
    @with_retry(max_retries=3, delay=1.0)
    def _sync_has_hash(self, user_id: int, item_hash: str) -> bool:
        if not self.client:
            return False
        res = (
            self.client.table("nm_hashes")
            .select("hash")
            .eq("user_id", user_id)
            .eq("hash", item_hash)
            .limit(1)
            .execute()
        )
        return bool(res.data and len(res.data) > 0)

    async def has_hash(self, user_id: int, item_hash: str) -> bool:
        try:
            return await asyncio.to_thread(self._sync_has_hash, user_id, item_hash)
        except Exception as e:
            logger.error(f"Error checking hash '{item_hash}' for user {user_id}: {e}")
            return False

    @with_retry(max_retries=3, delay=1.0)
    def _sync_add_hash(self, user_id: int, item_hash: str) -> bool:
        if not self.client:
            return False
        self.client.table("nm_hashes").insert({"hash": item_hash, "user_id": user_id}).execute()
        return True

    async def add_hash(self, user_id: int, item_hash: str) -> bool:
        try:
            return await asyncio.to_thread(self._sync_add_hash, user_id, item_hash)
        except Exception as e:
            logger.error(f"Error adding hash '{item_hash}' for user {user_id}: {e}")
            return False

    # --- Per-User Queue Operations ---
    @with_retry(max_retries=3, delay=1.0)
    def _sync_enqueue_message(
        self,
        user_id: int,
        source: str,
        msg_id: int,
        text: str,
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
    ) -> Optional[int]:
        if not self.client:
            return None
        res = (
            self.client.table("nm_queue")
            .insert(
                {
                    "user_id": user_id,
                    "source": str(source),
                    "msg_id": msg_id,
                    "text": text or "",
                    "media_type": media_type,
                    "media_file_id": media_file_id,
                    "status": "pending",
                }
            )
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0].get("id")
        return None

    async def enqueue_message(
        self,
        user_id: int,
        source: str,
        msg_id: int,
        text: str,
        media_type: Optional[str] = None,
        media_file_id: Optional[str] = None,
    ) -> Optional[int]:
        try:
            return await asyncio.to_thread(
                self._sync_enqueue_message,
                user_id,
                source,
                msg_id,
                text,
                media_type,
                media_file_id,
            )
        except Exception as e:
            logger.error(f"Error enqueueing message for user {user_id}: {e}")
            return None

    @with_retry(max_retries=3, delay=1.0)
    def _sync_get_next_queue_item(self, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if not self.client:
            return None
        query = self.client.table("nm_queue").select("*").eq("status", "pending")
        if user_id is not None:
            query = query.eq("user_id", user_id)
        res = query.order("id", desc=False).limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None

    async def get_next_queue_item(self, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(self._sync_get_next_queue_item, user_id)
        except Exception as e:
            logger.error(f"Error fetching next queue item: {e}")
            return None

    @with_retry(max_retries=3, delay=1.0)
    def _sync_update_queue_status(
        self, item_id: int, status: str, error_message: Optional[str] = None
    ) -> bool:
        if not self.client:
            return False
        payload: Dict[str, Any] = {"status": status}
        if error_message:
            payload["error_message"] = error_message
        self.client.table("nm_queue").update(payload).eq("id", item_id).execute()
        return True

    async def update_queue_status(
        self, item_id: int, status: str, error_message: Optional[str] = None
    ) -> bool:
        try:
            return await asyncio.to_thread(
                self._sync_update_queue_status, item_id, status, error_message
            )
        except Exception as e:
            logger.error(f"Error updating queue status {item_id}: {e}")
            return False

    @with_retry(max_retries=3, delay=1.0)
    def _sync_get_queue_stats(self, user_id: int) -> Dict[str, int]:
        if not self.client:
            return {"pending": 0, "published": 0, "rejected": 0, "failed": 0}
        stats = {}
        for status in ["pending", "published", "rejected", "failed"]:
            res = (
                self.client.table("nm_queue")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("status", status)
                .execute()
            )
            stats[status] = res.count or 0
        return stats

    async def get_queue_stats(self, user_id: int) -> Dict[str, int]:
        try:
            return await asyncio.to_thread(self._sync_get_queue_stats, user_id)
        except Exception as e:
            logger.error(f"Error getting queue stats for user {user_id}: {e}")
            return {"pending": 0, "published": 0, "rejected": 0, "failed": 0}


db = Database()
