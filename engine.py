import hashlib
import logging
import os
import re
from typing import Optional, Tuple
from telegram import Bot
from telegram.error import BadRequest
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


def normalize_channel_id(dest: str):
    target = dest.strip()
    if target.startswith("https://t.me/"):
        target = target.replace("https://t.me/", "")
    if target.startswith("t.me/"):
        target = target.replace("t.me/", "")

    if target.startswith("-100") and target[4:].isdigit():
        return int(target)
    elif target.startswith("-") and target[1:].isdigit():
        return int(target)
    elif target.isdigit():
        return int(target)
    elif not target.startswith("@"):
        return f"@{target}"
    return target


async def safe_send_message(bot: Bot, chat_id, text: str):
    """
    Sends message safely, retrying without Markdown if Telegram throws entity parsing errors.
    """
    chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        try:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown", disable_web_page_preview=True)
        except BadRequest:
            await bot.send_message(chat_id=chat_id, text=chunk, disable_web_page_preview=True)


class NewsEngine:
    async def scan_user_sources(self, user_id: int) -> int:
        count, _ = await self.scan_user_sources_with_report(user_id)
        return count

    async def scan_user_sources_with_report(self, user_id: int) -> Tuple[int, str]:
        settings = await db.get_user_settings(user_id)
        if not settings.sources:
            return 0, "⚠️ لیست منابع شما خالی است."

        is_auth = await user_client_manager.is_authorized(user_id)
        if not is_auth:
            return 0, "❌ اکانت تلگرام (یوزربات) متصل نیست! ابتدا دکمه QR را اسکن کنید."

        total_queued = 0
        reports = []

        for source in settings.sources:
            try:
                messages = await user_client_manager.fetch_channel_messages(user_id, source, limit=10)
                if not messages:
                    reports.append(f"📡 `{source}`: پیامی دریافت نشد (یا کانال خصوصی است و اکانت شما عضو آن نیست).")
                    continue

                new_count = 0
                dup_count = 0
                for msg in reversed(messages):
                    text = msg.message or msg.text or ""
                    if not text and not msg.media:
                        continue

                    h = compute_content_hash(source, msg.id, text)
                    if await db.has_hash(user_id, h):
                        dup_count += 1
                        continue

                    media_type, media_path = await user_client_manager.download_media(
                        user_id, msg, allow_photo=settings.send_photo, allow_video=settings.send_video
                    )

                    queue_id = await db.enqueue_message(
                        user_id=user_id, source=source, msg_id=msg.id, text=text,
                        media_type=media_type, media_file_id=media_path
                    )
                    if queue_id:
                        await db.add_hash(user_id, h)
                        total_queued += 1
                        new_count += 1

                reports.append(f"📡 `{source}`: {len(messages)} پیام بررسی شد ({new_count} جدید، {dup_count} تکراری)")
            except Exception as e:
                reports.append(f"⚠️ `{source}`: خطا در خواندن ({str(e)[:40]})")

        if total_queued > 0:
            logger.info(f"User {user_id}: Successfully queued {total_queued} new posts.")
        return total_queued, "\n".join(reports)

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
            dest_chat_id = normalize_channel_id(settings.dest_channel)

            # Send photo
            if media_type == "photo" and media_path and os.path.exists(media_path):
                if len(final_text) <= 1024:
                    with open(media_path, "rb") as photo_file:
                        try:
                            await bot.send_photo(chat_id=dest_chat_id, photo=photo_file, caption=final_text, parse_mode="Markdown")
                        except BadRequest:
                            photo_file.seek(0)
                            await bot.send_photo(chat_id=dest_chat_id, photo=photo_file, caption=final_text)
                else:
                    with open(media_path, "rb") as photo_file:
                        await bot.send_photo(chat_id=dest_chat_id, photo=photo_file)
                    await safe_send_message(bot, dest_chat_id, final_text)

            # Send video
            elif media_type == "video" and media_path and os.path.exists(media_path):
                if len(final_text) <= 1024:
                    with open(media_path, "rb") as video_file:
                        try:
                            await bot.send_video(chat_id=dest_chat_id, video=video_file, caption=final_text, parse_mode="Markdown")
                        except BadRequest:
                            video_file.seek(0)
                            await bot.send_video(chat_id=dest_chat_id, video=video_file, caption=final_text)
                else:
                    with open(media_path, "rb") as video_file:
                        await bot.send_video(chat_id=dest_chat_id, video=video_file)
                    await safe_send_message(bot, dest_chat_id, final_text)

            # Send text only
            else:
                await safe_send_message(bot, dest_chat_id, final_text)

            await db.update_queue_status(item_id, "published")
            logger.info(f"Published item #{item_id} for user {user_id} to {dest_chat_id}")

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
