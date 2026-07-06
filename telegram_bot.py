"""
telegram_bot.py
----------------
Handles sending the formatted daily summary to Telegram via the Telegram Bot
API, with retry logic and Markdown-escaping safety.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

import config

logger = logging.getLogger("telegram_bot")

# Callback data used by the "Add All Events to iPhone" inline button, so the
# background listener (bot_listener.py) knows how to respond to taps.
ICS_BUTTON_CALLBACK_DATA = "ics_add_all"


def _get_bot() -> telegram.Bot:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (check your .env file)")
    return telegram.Bot(token=config.TELEGRAM_BOT_TOKEN)


async def _send_async(message: str) -> None:
    bot = _get_bot()
    if not config.TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set (check your .env file)")

    await bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text=message,
        parse_mode=telegram.constants.ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


def send_message(message: str, max_retries: Optional[int] = None) -> bool:
    """
    Send `message` to the configured Telegram chat, retrying on transient
    failures. Returns True on success, False if all retries were exhausted.

    Uses python-telegram-bot's async API under the hood via asyncio.run(),
    so this function itself stays a plain synchronous call for easy use from
    the scheduler.
    """
    import asyncio

    retries = max_retries if max_retries is not None else config.MAX_RETRIES

    for attempt in range(1, retries + 1):
        try:
            asyncio.run(_send_async(message))
            logger.info("Telegram message sent successfully (attempt %d)", attempt)
            return True
        except TelegramError as exc:
            logger.warning("Telegram send failed (attempt %d/%d): %s", attempt, retries, exc)
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error sending Telegram message: %s", exc, exc_info=True)

        if attempt < retries:
            sleep_for = config.RETRY_BACKOFF_SECONDS * attempt
            logger.info("Retrying Telegram send in %ds...", sleep_for)
            time.sleep(sleep_for)

    logger.error("All %d attempt(s) to send Telegram message failed", retries)
    return False


def _build_ics_keyboard() -> InlineKeyboardMarkup:
    """
    Inline button shown under the .ics document.

    Important honesty note: Telegram bots cannot remotely trigger iOS's
    native "Add All Events to Calendar" action — that action only appears
    when the *user* taps the .ics file/attachment itself, because it's
    handled by iOS's own document preview, not by the bot. This button
    instead gives one-tap access to clear import instructions (and can
    re-send the file if it's missing), so the flow still ends in exactly
    one tap on the actual file to import everything.
    """
    button = InlineKeyboardButton(
        text="📅 Add All Events to iPhone",
        callback_data=ICS_BUTTON_CALLBACK_DATA,
    )
    return InlineKeyboardMarkup([[button]])


async def _send_document_async(file_path: Path, caption: str) -> None:
    bot = _get_bot()
    if not config.TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set (check your .env file)")

    with open(file_path, "rb") as f:
        await bot.send_document(
            chat_id=config.TELEGRAM_CHAT_ID,
            document=f,
            filename=file_path.name,
            caption=caption,
            parse_mode=telegram.constants.ParseMode.MARKDOWN,
            reply_markup=_build_ics_keyboard(),
        )


def send_ics_document(file_path: Path, caption: str, max_retries: Optional[int] = None) -> bool:
    """
    Send a generated .ics file to the configured Telegram chat, with the
    "📅 Add All Events to iPhone" inline button attached, retrying on
    transient failures. Returns True on success, False if all retries were
    exhausted or the file doesn't exist.
    """
    import asyncio

    if not file_path or not Path(file_path).exists():
        logger.error("Cannot send .ics document — file does not exist: %s", file_path)
        return False

    retries = max_retries if max_retries is not None else config.MAX_RETRIES

    for attempt in range(1, retries + 1):
        try:
            asyncio.run(_send_document_async(Path(file_path), caption))
            logger.info(".ics document sent successfully (attempt %d): %s", attempt, file_path)
            return True
        except TelegramError as exc:
            logger.warning(".ics send failed (attempt %d/%d): %s", attempt, retries, exc)
        except OSError as exc:
            logger.error("File error while sending .ics document: %s", exc, exc_info=True)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected error sending .ics document: %s", exc, exc_info=True)

        if attempt < retries:
            sleep_for = config.RETRY_BACKOFF_SECONDS * attempt
            logger.info("Retrying .ics send in %ds...", sleep_for)
            time.sleep(sleep_for)

    logger.error("All %d attempt(s) to send .ics document failed", retries)
    return False


def send_message_chunked(message: str, chunk_size: int = 4000) -> bool:
    """
    Telegram caps messages at 4096 characters. If a daily summary somehow
    exceeds that (e.g. an unusually busy news day with no filtering), split
    it on blank-line boundaries and send sequentially.
    """
    if len(message) <= chunk_size:
        return send_message(message)

    chunks = []
    current = ""
    for block in message.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > chunk_size:
            if current:
                chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)

    success = True
    for i, chunk in enumerate(chunks, start=1):
        logger.info("Sending message chunk %d/%d", i, len(chunks))
        success = send_message(chunk) and success
    return success
