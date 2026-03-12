"""LINE Bot webhook server using Flask."""

import logging
from flask import Flask, request, abort
from linebot.v3.exceptions import InvalidSignatureError
from bot.line_handlers import handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    logger.info(f"Received webhook: {body[:200]}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        logger.error("Invalid signature")
        abort(400)

    return "OK"


@app.route("/health", methods=["GET"])
def health():
    return "OK"


if __name__ == "__main__":
    logger.info("Starting LINE Bot server on port 5000")
    app.run(host="0.0.0.0", port=5000)
