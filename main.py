import asyncio
import logging
import time
from typing import Dict
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from config import config
from database import db
from user_client import user_client_manager
from engine import engine
from web_server import start_web_server
from bot.handlers import start_command, callback_handler, message_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def background_worker(bot):
    """
    Multi-tenant worker loop: iterates through all authorized active users
    and manages isolated scanning and publishing for each.
    """
    logger.info("Multi-tenant background worker loop started.")
    last_scan_times: Dict[int, float] = {}

    while True:
        try:
            running_users = await db.get_all_running_users()
            now = time.time()

            for uid in running_users:
                try:
                    settings = await db.get_user_settings(uid)
                    if not settings.running or not settings.sources or not settings.dest_channel:
                        continue

                    scan_interval = max(settings.interval_min * 60, 60)
                    last_scan = last_scan_times.get(uid, 0.0)

                    # Scheduled channel scan per user
                    if now - last_scan >= scan_interval:
                        await engine.scan_user_sources(uid)
                        last_scan_times[uid] = time.time()

                    # Process one pending item per user per tick
                    published = await engine.publish_user_tick(uid, bot)
                    if published:
                        await asyncio.sleep(2)

                except Exception as e:
                    logger.error(f"Error processing worker for user {uid}: {e}")

            await asyncio.sleep(10)

        except asyncio.CancelledError:
            logger.info("Background worker loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Global error in background worker: {e}", exc_info=True)
            await asyncio.sleep(15)


async def main():
    if not config.bot_token or not config.owner_id:
        logger.error("BOT_TOKEN or OWNER_ID/ADMIN_ID is missing in configuration! Exiting.")
        return

    logger.info(f"Starting News Manager Bot (Owner: {config.owner_id})...")

    # Pre-connect owner userbot if session string exists
    try:
        user_client = await user_client_manager.get_or_create_client(config.owner_id)
        if await user_client.is_user_authorized():
            me = await user_client.get_me()
            logger.info(f"Owner userbot pre-connected as: {getattr(me, 'first_name', 'User')}")
    except Exception as e:
        logger.warning(f"Initial userbot connection attempt: {e}")

    # Build PTB Application
    application = ApplicationBuilder().token(config.bot_token).build()

    # Register Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    # Start Health Check Web Server
    web_runner = await start_web_server()

    # Start Bot & Background Worker
    async with application:
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Telegram Bot polling started.")

        worker_task = asyncio.create_task(background_worker(application.bot))

        try:
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Stopping bot and services...")
        finally:
            worker_task.cancel()
            await application.updater.stop()
            await application.stop()
            await web_runner.cleanup()
            for uid, c in user_client_manager.clients.items():
                if c.is_connected():
                    await c.disconnect()
            logger.info("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
