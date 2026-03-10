"""Dlogic Telegram Agent - Entry point."""

import logging
import sys

from config import TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, CLAUDE_MODEL
from bot.handlers import create_app

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main():
    # Validate config
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Create .env.local with your bot token.")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY is not set. Create .env.local with your API key.")
        sys.exit(1)

    logger.info(f"Starting Dlogic Agent with model: {CLAUDE_MODEL}")

    app = create_app()
    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
