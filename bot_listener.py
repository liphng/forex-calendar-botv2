"""
bot_listener.py
----------------
A small, optional background listener that responds when the user taps the
"📅 Add All Events to iPhone" inline button attached to the daily .ics
document.

Why this exists: Telegram bots cannot programmatically trigger iOS's native
"Add All Events to Calendar" action — that UI only appears when the user
taps the .ics *file* itself, handled entirely by iOS's own document
preview. This listener's job is just to answer the button tap with a clear,
friendly one-tap-import instruction (and can resend the file if needed), so
the whole experience still feels like "one tap" even though the technical
trigger is tapping the file, not the inline button.

Runs via long-polling in its own thread alongside the APScheduler-based
scheduler (see main.py), so it does not block the daily send job.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

import config
from telegram_bot import ICS_BUTTON_CALLBACK_DATA

logger = logging.getLogger("bot_listener")

IMPORT_INSTRUCTIONS = (
    "📲 *How to import today's events:*\n\n"
    "1. Scroll up and tap the *.ics file* attached above (not this button)\n"
    "2. Tap *\"Add All\"* in the preview that opens\n"
    "3. All of today's forex events are added to Apple Calendar instantly\n"
    "4. iPhone reminders/lock-screen alerts fire automatically at each "
    "event's reminder time\n\n"
    "_Using Android or Google Calendar? Tap the file and choose \"Open with "
    "Google Calendar\" or \"Import\" instead._"
)


async def _handle_ics_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    try:
        await query.answer()  # acknowledge the tap so the button stops "loading"
        await query.message.reply_text(
            IMPORT_INSTRUCTIONS,
            parse_mode="Markdown",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to handle .ics button callback: %s", exc, exc_info=True)


def build_application() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (check your .env file)")

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(
        CallbackQueryHandler(_handle_ics_button, pattern=f"^{ICS_BUTTON_CALLBACK_DATA}$")
    )
    return application


def run_listener_blocking() -> None:
    """
    Start long-polling for callback queries. Blocks the calling thread, so
    callers running this alongside the scheduler should start it in a
    background daemon thread (see main.py).
    """
    logger.info("Starting Telegram callback-query listener (background thread).")
    application = build_application()
    # stop_signals=None: this typically runs in a non-main thread, and
    # python-telegram-bot's default signal handling only works on the main
    # thread — disabling it avoids a crash there. The main process's own
    # signal handling (systemd/Docker/Ctrl+C) still governs shutdown.
    application.run_polling(stop_signals=None, drop_pending_updates=True)
