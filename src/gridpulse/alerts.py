"""Send a short alert to Telegram. Without credentials it only logs, so dev and CI stay quiet."""

import logging
import os

import httpx

log = logging.getLogger(__name__)


def send_alert(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        log.warning("ALERT (no Telegram configured): %s", text)
        return False
    resp = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"GridPulse: {text}"},
        timeout=20,
    )
    resp.raise_for_status()
    return True
