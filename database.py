import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from dataclasses import asdict
from supabase import create_client, Client
from config import config, SettingsConfig

logger = logging.getLogger(__name__)

CACHE_FILE = "local_cache.json"


def with_retry(max_retries: int = 3, delay: float = 1.0):
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    if attempt < max_retries:
                        time.sleep(delay * attempt)
            logger.warning(f"DB call '{func.__name__}' failed after {max_retries} attempts: {last_err}")
            raise last_err
        return wrapper
    return decorator


class Database:
    def __init__(self):
        self.client: Optional[Client] = None
        self._cache: Dict[str, Any] = {}
        self._load_local_cache()
        self._init_client()

    def _load_local_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                logger.info(f"Loaded {len(self._cache)} items from local cache.")
            except Exception as e:
                logger.error(f"Error loading local cache: {e}")

    def _save_local_cache(self):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving local cache: {e}")

    def _init_client(self):
        if config.supabase_url and config.supabase_key:
            try:
                self.client = create_client(config.supabase_url, config.supabase_key)
                logger.info("Supabase client initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase: {e}")

    @with_retry(max_retries=2, delay=0.5)
    def _sync_get_kv(self, key: str) -> Optional[Any]:
        if not self.client:
            return None
        res = self.client.table("nm_kv").select("value").eq("key", key).limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0].get("value")
        return None

    async def get_kv(self, key: str, default: Any = None) -> Any:
        # ۱. ابتدا از کش محلی سریع می‌خوانیم
        if key in self._cache:
            return self._cache[key]

        # ۲. اگر در کش نبود، از سوپابیس استعلام می‌گیریم
        try:
            val = await asyncio.to_thread(self._sync_get_kv, key)
            if val is not None:
                self._cache[key] = val
                self._save_local_cache()
                return val
        except Exception as e:
            logger.debug(f"Could not fetch '{key}' from Supabase: {e}")

        return default

    @with_retry(max_retries=2, delay=0.5)
    def _sync_set_kv(self, key: str, value: Any) -> bool:
        if not self.client:
            return False
        self.client.table("nm_kv").upsert({"key": key, "value": value}).execute()
        return True

    async def set_kv(self, key: str, value: Any) -> bool:
        # ۱. بلافاصله در کش رم و فایل محلی ذخیره می‌شود (بدون تاخیر)
        self._cache[key] = value
        self._save_local_cache()

        # ۲. ذخیره هم‌زمان در سوپابیس
        try:
            return await asyncio.to_thread(self._sync_set_kv, key, value)
        except Exception as e:
            logger.warning(f"Background sync to Supabase failed for '{key}': {e}")
            return True

    # --- User Access Management ---
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
            return False
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

    # --- Per-User Settings ---
    async def get_user_settings(self, user_id: int) -> SettingsConfig:
        key = f"settings_{user_id}"
        stored = await self.get_kv(key, default=None)
        if not stored or not isinstance(stored, dict):
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

    # --- Deduplication Hashes ---
    @with_retry(max_retries=2, delay=0.5)
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
        cache_key = f"hash_{user_id}_{item_hash}"
        if cache_key in self._cache:
            return True
        try:
            exists = await asyncio.to_thread(self._sync_has_hash, user_id, item_hash)
            if exists:
                self._cache[cache_key] = True
            return exists
        except Exception:
            return False

    @with_retry(max_retries=2, delay=0.5)
    def _sync_add_hash(self, user_id: int, item_hash: str) -> bool:
        if not self.client:
            return False
        self.client.table("nm_hashes").insert({"hash": item_hash, "user_id": user_id}).execute()
        return True

    async def add_hash(self, user_id: int, item_hash: str) -> bool:
        cache_key = f"hash_{user_id}_{item_hash}"
        self._cache[cache_key] = True
        try:
            return await asyncio.to_thread(self._sync_add_hash, user_id, item_hash)
        except Exception:
            return True

    # --- Queue ---
    @with_retry(max_retries=2, delay=0.5)
    def _sync_enqueue_message(
        self, user_id: int, source: str, msg_id: int, text: str, media_type: Optional[str], media_file_id: Optional[str]
    ) -> Optional[int]:
        if not self.client:
            return None
        res = (
            self.client.table("nm_queue")
            .insert({
                "user_id": user_id,
                "source": str(source),
                "msg_id": msg_id,
                "text": text or "",
                "media_type": media_type,
                "media_file_id": media_file_id,
                "status": "pending",
            })
            .execute()
        )
        if res.data and len(res.data) > 0:
            return res.data[0].get("id")
        return None

    async def enqueue_message(
        self, user_id: int, source: str, msg_id: int, text: str, media_type: Optional[str] = None, media_file_id: Optional[str] = None
    ) -> Optional[int]:
        try:
            return await asyncio.to_thread(
                self._sync_enqueue_message, user_id, source, msg_id, text, media_type, media_file_id
            )
        except Exception as e:
            logger.error(f"Error enqueueing message for user {user_id}: {e}")
            return None

    @with_retry(max_retries=2, delay=0.5)
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

    @with_retry(max_retries=2, delay=0.5)
    def _sync_update_queue_status(self, item_id: int, status: str, error_message: Optional[str] = None) -> bool:
        if not self.client:
            return False
        payload: Dict[str, Any] = {"status": status}
        if error_message:
            payload["error_message"] = error_message
        self.client.table("nm_queue").update(payload).eq("id", item_id).execute()
        return True

    async def update_queue_status(self, item_id: int, status: str, error_message: Optional[str] = None) -> bool:
        try:
            return await asyncio.to_thread(self._sync_update_queue_status, item_id, status, error_message)
        except Exception as e:
            logger.error(f"Error updating queue status {item_id}: {e}")
            return False

    @with_retry(max_retries=2, delay=0.5)
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
        except Exception:
            return {"pending": 0, "published": 0, "rejected": 0, "failed": 0}

async def clear_user_hashes(self, user_id: int) -> int:
        """پاک‌سازی کامل تمام رکوردهای تکراری از رم، فایل و سوپابیس"""
        keys_to_del = [k for k in list(self._cache.keys()) if k.startswith(f"hash_{user_id}_")]
        for k in keys_to_del:
            del self._cache[k]
        self._save_local_cache()

        if self.client:
            try:
                await asyncio.to_thread(
                    lambda: self.client.table("nm_hashes").delete().eq("user_id", user_id).execute()
                )
            except Exception as e:
                logger.error(f"Error truncating hashes in DB: {e}")

        return len(keys_to_del)
db = Database()
