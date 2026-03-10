"""Unified entry point - runs both LINE Bot (webhook) and Telegram Bot (polling) together."""

import logging
import sys
import threading
import signal

from flask import Flask, request, abort
from linebot.v3.exceptions import InvalidSignatureError

from config import TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, CLAUDE_MODEL, LINE_CHANNEL_SECRET
from bot.handlers import create_app as create_telegram_app
from bot.line_handlers import handler as line_handler, load_memory as load_line_memory

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# --- Flask app for LINE Bot ---
flask_app = Flask(__name__)


@flask_app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    logger.info(f"LINE webhook: {body[:200]}")
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("Invalid LINE signature")
        abort(400)
    return "OK"


@flask_app.route("/health", methods=["GET"])
def health():
    return "OK"


# --- Telegram bot in background thread ---
def run_telegram_polling():
    """Run Telegram bot polling in a daemon thread using low-level async API."""
    import asyncio

    async def _run():
        tg_app = create_telegram_app()
        async with tg_app:
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot polling started successfully")
            # Keep running until thread is killed (daemon thread)
            stop_event = asyncio.Event()
            await stop_event.wait()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except Exception as e:
        logger.error(f"Telegram polling error: {e}", exc_info=True)


def main():
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY is not set")
        sys.exit(1)

    load_line_memory()

    # Start Telegram polling in background thread (if token exists)
    if TELEGRAM_BOT_TOKEN:
        tg_thread = threading.Thread(target=run_telegram_polling, daemon=True)
        tg_thread.start()
        logger.info("Telegram bot thread launched")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set, skipping Telegram bot")

    # Start Flask (LINE webhook) in foreground
    if LINE_CHANNEL_SECRET:
        import os
        port = int(os.environ.get("PORT", 5000))
        logger.info(f"Starting LINE Bot + Telegram Bot on port {port}")
        logger.info(f"Model: {CLAUDE_MODEL}")
        flask_app.run(host="0.0.0.0", port=port)
    else:
        logger.warning("LINE_CHANNEL_SECRET not set, running Telegram only")
        run_telegram_polling()


# For gunicorn: `gunicorn app:flask_app`
app = flask_app

if __name__ == "__main__":
    main()
