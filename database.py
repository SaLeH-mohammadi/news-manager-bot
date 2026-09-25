import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set
from dataclasses import asdict
from config import config, SettingsConfig

logger = logging.getLogger(__name__)

# Optional Supabase import
try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = None

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
STORE_FILE = os.path.join(DATA_DIR, "bot_store.json")


class Database:
    """
    Bulletproof Dual-Store Engine:
    1. Local Atomic JSON Store: Instant (0ms), never crashes, never wiped, cross-platform.
    2. Cloud Supabase Backup: Optional async background sync for multi-server setups.
    """
    def __init__(self):
        self.client: Optional[Client] = None
        self._kv: Dict[str, Any] = {}
        self._hashes: Dict[int, Set[str]] = {}
        self._queue: List[Dict[str, Any]] = []
        self._next_qid: int = 1
        self._load_local_store()
        self._init_supabase()

    def _load_local_store(self):
        if os.path.exists(STORE_FILE):
            try:
                with open(STORE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._kv = data.get("kv", {})
                    raw_hashes = data.get("hashes", {})
                    self._hashes = {int(k): set(v) for k, v in raw_hashes.items()}
                    self._queue = data.get("queue", [])
                    self._next_qid = data.get("next_qid", 1)
                logger.info(f"Loaded local store: {len(self._kv)} keys, {len(self._queue)} queue items.")
            except Exception as e:
                logger.error(f"Error loading local store: {e}")

    def _save_local_store(self):
        try:
            data = {
                "kv": self._kv,
                "hashes": {str(k): list(v) for k, v in self._hashes.items()},
                "queue": self._queue,
                "next_qid": self._next_qid,
            }
            tmp_file = STORE_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, STORE_FILE)
        except Exception as e:
            logger.error(f"Error saving local store: {e}")

    def _init_supabase(self):
        if create_client and config.supabase_url and config.supabase_key:
            try:
                self.client = create_client(config.supabase_url, config.supabase_key)
                logger.info("Supabase client initialized.")
            except Exception as e:
                logger.warning(f"Supabase connection warning: {e}")

    # ================= KV OPERATIONS =================

    def _sync_supabase_get_kv(self, key: str) -> Optional[Any]:
        if not self.client:
            return None
        try:
            res = self.client.table("nm_kv").select("value").eq("key", key).limit(1).execute()
            if res.data and len(res.data) > 0:
                return res.data[0].get("value")
        except Exception as e:
            logger.debug(f"Supabase get_kv error: {e}")
        return None

    def _sync_supabase_set_kv(self, key: str, value: Any) -> bool:
        if not self.client:
            return False
        try:
            self.client.table("nm_kv").upsert({"key": key, "value": value}).execute()
            return True
        except Exception as e:
            logger.debug(f"Supabase set_kv error: {e}")
            return False

    async def get_kv(self, key: str, default: Any = None) -> Any:
        # 1. Local memory/file (instant, zero-latency, 100% reliable)
        if key in self._kv:
            return self._kv[key]

        # 2. Supabase fallback
        if self.client:
            cloud_val = await asyncio.to_thread(self._sync_supabase_get_kv, key)
            if cloud_val is not None:
                self._kv[key] = cloud_val
                self._save_local_store()
                return cloud_val

        return default

    async def set_kv(self, key: str, value: Any) -> bool:
        # 1. Update memory & atomic local file
        self._kv[key] = value
        self._save_local_store()

        # 2. Async non-blocking background sync to Supabase
        if self.client:
            asyncio.create_task(asyncio.to_thread(self._sync_supabase_set_kv, key, value))

        return True

    # ================= USER ACCESS WHITELIST =================

    async def get_authorized_users(self) -> List[int]:
        users = await self.get_kv("authorized_users", default=[])
        if not isinstance(users, list):
            users = []
        if config.owner_id and config.owner_id not in users:
            users.append(config.owner_id)
            await self.set_kv("authorized_users", users)
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

    # ================= PER-USER SETTINGS =================

    async def get_user_settings(self, user_id: int) -> SettingsConfig:
        key = f"settings_{user_id}"
        stored = await self.get_kv(key, default=None)

        # NEVER wipe existing database on read! Return clean default only if never set.
        if not stored or not isinstance(stored, dict):
            return SettingsConfig()

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

    # ================= DEDUPLICATION HASHES =================

    async def has_hash(self, user_id: int, item_hash: str) -> bool:
        user_hashes = self._hashes.get(user_id)
        if user_hashes and item_hash in user_hashes:
            return True

        if self.client:
            try:
                res = (
                    self.client.table("nm_hashes")
                    .select("hash")
                    .eq("user_id", user_id)
                    .eq("hash", item_hash)
                    .limit(1)
                    .execute()
                )
                if res.data and len(res.data) > 0:
                    self._hashes.setdefault(user_id, set()).add(item_hash)
                    return True
            except Exception:
                pass

        return False

    async def add_hash(self, user_id: int, item_hash: str) -> bool:
        self._hashes.setdefault(user_id, set()).add(item_hash)
        self._save_local_store()

        if self.client:
            asyncio.create_task(
                asyncio.to_thread(
                    lambda: self.client.table("nm_hashes").insert({"user_id": user_id, "hash": item_hash}).execute()
                )
            )
        return True

    async def clear_user_hashes(self, user_id: int) -> int:
        count = len(self._hashes.get(user_id, set()))
        if user_id in self._hashes:
            self._hashes[user_id].clear()
            self._save_local_store()

        if self.client:
            asyncio.create_task(
                asyncio.to_thread(
                    lambda: self.client.table("nm_hashes").delete().eq("user_id", user_id).execute()
                )
            )
        return count

    # ================= QUEUE OPERATIONS =================

    async def enqueue_message(
        self, user_id: int, source: str, msg_id: int, text: str, media_type: Optional[str] = None, media_file_id: Optional[str] = None
    ) -> Optional[int]:
        qid = self._next_qid
        self._next_qid += 1

        item = {
            "id": qid,
            "user_id": user_id,
            "source": source,
            "msg_id": msg_id,
            "text": text or "",
            "media_type": media_type,
            "media_file_id": media_file_id,
            "status": "pending",
            "error_message": None,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._queue.append(item)
        self._save_local_store()

        if self.client:
            asyncio.create_task(
                asyncio.to_thread(
                    lambda: self.client.table("nm_queue").insert({
                        "user_id": user_id, "source": source, "msg_id": msg_id,
                        "text": text or "", "media_type": media_type, "media_file_id": media_file_id, "status": "pending"
                    }).execute()
                )
            )
        return qid

    async def get_next_queue_item(self, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        for item in self._queue:
            if item.get("status") == "pending":
                if user_id is None or item.get("user_id") == user_id:
                    return item
        return None

    async def update_queue_status(self, item_id: int, status: str, error_message: Optional[str] = None) -> bool:
        updated = False
        for item in self._queue:
            if item.get("id") == item_id:
                item["status"] = status
                if error_message:
                    item["error_message"] = error_message
                updated = True
                break

        if updated:
            self._save_local_store()
            if self.client:
                payload = {"status": status}
                if error_message:
                    payload["error_message"] = error_message
                asyncio.create_task(
                    asyncio.to_thread(lambda: self.client.table("nm_queue").update(payload).eq("id", item_id).execute())
                )
        return updated

    async def get_queue_stats(self, user_id: int) -> Dict[str, int]:
        stats = {"pending": 0, "published": 0, "rejected": 0, "failed": 0}
        for item in self._queue:
            if item.get("user_id") == user_id:
                st = item.get("status")
                if st in stats:
                    stats[st] += 1
        return stats


db = Database()
