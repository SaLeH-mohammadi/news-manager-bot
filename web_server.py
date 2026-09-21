import logging
from aiohttp import web
from config import config

logger = logging.getLogger(__name__)


async def index(request):
    return web.json_response(
        {
            "status": "ok",
            "service": "news-manager-bot",
            "framework": "python-telegram-bot",
        }
    )


async def health(request):
    return web.json_response({"status": "healthy"})


def create_web_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    return app


async def start_web_server():
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()
    logger.info(f"Health-check web server started on port {config.port}")
    return runner
