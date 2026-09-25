import hashlib
import logging
import os
import re
from typing import Optional
from telegram import Bot
from database import db
from user_client import user_client_manager
from ai_service import ai_service

logger = logging.getLogger(__name__)


def compute_content_hash(source: str, msg_id: int, text: Optional[str]) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip().lower()
    if len(cleaned) > 20:
        return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    raw = f"{source}:{msg_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class NewsEngine:
    async def scan_user_sources(self, user_id: int) -> int:
        settings = await db.get_user_settings(user_id)
        if not settings.sources:
            return 0

        is_auth = await user_client_manager.is_authorized(user_id)
        if not is_auth:
            logger.warning(f"Userbot client for user {user_id} not authorized.")
            return 0

        total_queued = 0
        for source in settings.sources:
            try:
                messages = await user_client_manager.fetch_channel_messages(user_id, source, limit=10)
                for msg in reversed(messages):
                    text = msg.message or msg.text or ""
                    if not text and not msg.media:
                        continue

                    h = compute_content_hash(source, msg.id, text)
                    if await db.has_hash(user_id, h):
                        continue

                    media_type, media_path = await user_client_manager.download_media(
                        user_id,
                        msg,
                        allow_photo=settings.send_photo,
                        allow_video=settings.send_video,
                    )

                    # ابتدا در دیتابیس ثبت می‌شود
                    queue_id = await db.enqueue_message(
                        user_id=user_id,
                        source=source,
                        msg_id=msg.id,
                        text=text,
                        media_type=media_type,
                        media_file_id=media_path,
                    )

                    # فقط در صورت ذخیره موفق، به لیست هش‌ها اضافه شده و شمارش می‌شود
                    if queue_id:
                        await db.add_hash(user_id, h)
                        total_queued += 1
                    else:
                        logger.error(f"Failed to enqueue message {msg.id} for user {user_id}")

            except Exception as e:
                logger.error(f"Error scanning source '{source}' for user {user_id}: {e}")

        if total_queued > 0:
            logger.info(f"User {user_id}: Successfully queued {total_queued} new posts.")
        return total_queued

    async def publish_user_tick(self, user_id: int, bot: Bot) -> bool:
        settings = await db.get_user_settings(user_id)
        if not settings.dest_channel:
            return False

        item = await db.get_next_queue_item(user_id=user_id)
        if not item:
            return False

        item_id = item["id"]
        raw_text = item.get("text", "")
        media_type = item.get("media_type")
        media_path = item.get("media_file_id")

        await db.update_queue_status(item_id, "processing")

        try:
            rewritten = await ai_service.rewrite_news(raw_text)
            if not rewritten:
                await db.update_queue_status(item_id, "rejected", "AI rejected or empty text.")
                self._cleanup_file(media_path)
                return True

            signature = settings.signature.strip()
            final_text = f"{rewritten}\n\n{signature}" if signature else rewritten

            dest_channel = settings.dest_channel.strip()
            dest_chat_id = int(dest_channel) if dest_channel.lstrip("-").isdigit() else dest_channel

            if media_type == "photo" and media_path and os.path.exists(media_path):
                if len(final_text) <= 1024:
                    with open(media_path, "rb") as photo_file:
                        await bot.send_photo(chat_id=dest_chat_id, photo=photo_file, caption=final_text)
                else:
                    with open(media_path, "rb") as photo_file:
                        await bot.send_photo(chat_id=dest_chat_id, photo=photo_file)
                    await bot.send_message(chat_id=dest_chat_id, text=final_text, disable_web_page_preview=True)
            elif media_type == "video" and media_path and os.path.exists(media_path):
                if len(final_text) <= 1024:
                    with open(media_path, "rb") as video_file:
                        await bot.send_video(chat_id=dest_chat_id, video=video_file, caption=final_text)
                else:
                    with open(media_path, "rb") as video_file:
                        await bot.send_video(chat_id=dest_chat_id, video=video_file)
                    await bot.send_message(chat_id=dest_chat_id, text=final_text, disable_web_page_preview=True)
            else:
                await bot.send_message(chat_id=dest_chat_id, text=final_text, disable_web_page_preview=True)

            await db.update_queue_status(item_id, "published")
            logger.info(f"Published item #{item_id} for user {user_id} to {dest_channel}")

        except Exception as e:
            logger.error(f"Failed to publish item #{item_id} for user {user_id}: {e}")
            await db.update_queue_status(item_id, "failed", str(e))
        finally:
            self._cleanup_file(media_path)

        return True

    def _cleanup_file(self, path: Optional[str]):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                logger.error(f"Error removing temp media file {path}: {e}")


engine = NewsEngine()
