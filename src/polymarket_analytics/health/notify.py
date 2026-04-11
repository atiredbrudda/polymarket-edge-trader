"""Dual-channel alert delivery — Telegram bot + macOS native notifications.

Per D-01/D-02/D-03: Both channels fire for every alert. Neither blocks
the other on failure. Notification failure never raises — best-effort only.
"""
import os
import subprocess
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")


def send_alert(title: str, message: str) -> None:
    """Send alert to both Telegram and macOS. Best-effort — never raises."""
    _send_telegram(title, message)
    _send_macos_notification(title, message)


def _send_telegram(title: str, message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    text = f"*{title}*\n{message}"
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def _send_macos_notification(title: str, message: str) -> None:
    safe_title = title.replace('"', "'")
    safe_message = message.replace('"', "'")
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_message}" with title "{safe_title}"'],
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass
