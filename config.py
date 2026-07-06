"""
config.py
---------
Central configuration for the Forex Economic Calendar Reminder bot.

All values can be overridden via environment variables (.env file).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment variables from .env
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str, default: List[str]) -> List[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [item.strip().upper() for item in val.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Telegram settings
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Timezone / scheduling
# ---------------------------------------------------------------------------
TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Singapore")  # GMT+8, no DST
SEND_HOUR: int = int(os.getenv("SEND_HOUR", "6"))
SEND_MINUTE: int = int(os.getenv("SEND_MINUTE", "0"))

# Weekly outlook schedule. Monday is 0, Sunday is 6.
ENABLE_WEEKLY_UPDATE: bool = _get_bool("ENABLE_WEEKLY_UPDATE", True)
WEEKLY_SEND_DAY: int = int(os.getenv("WEEKLY_SEND_DAY", "0"))
WEEKLY_SEND_HOUR: int = int(os.getenv("WEEKLY_SEND_HOUR", str(SEND_HOUR)))
WEEKLY_SEND_MINUTE: int = int(os.getenv("WEEKLY_SEND_MINUTE", str(SEND_MINUTE)))

# ---------------------------------------------------------------------------
# Data source
# ---------------------------------------------------------------------------
# Primary source: Forex Factory's own public JSON feed (used by their embeddable
# widgets). This is far more reliable than scraping the JS-rendered HTML page,
# which sits behind bot-detection and changes markup frequently.
FF_JSON_URL: str = os.getenv(
    "FF_JSON_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
)

# Fallback: the human-facing calendar page, scraped with Selenium/Playwright
# if the JSON feed is unreachable or returns malformed data.
FF_CALENDAR_URL: str = os.getenv(
    "FF_CALENDAR_URL", "https://www.forexfactory.com/calendar"
)

USER_AGENT: str = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF_SECONDS: int = int(os.getenv("RETRY_BACKOFF_SECONDS", "5"))

# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
# Only include these impact levels. Options: High, Medium, Low
IMPACT_FILTER: List[str] = _get_list("IMPACT_FILTER", ["HIGH", "MEDIUM"])

# Only include these currencies
CURRENCY_FILTER: List[str] = _get_list(
    "CURRENCY_FILTER", ["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"]
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR: Path = BASE_DIR / "data"
LOG_DIR: Path = BASE_DIR / "logs"
EVENTS_JSON_PATH: Path = DATA_DIR / "events_today.json"
WEEK_EVENTS_JSON_PATH: Path = DATA_DIR / "events_week.json"
SENT_FLAG_PATH: Path = DATA_DIR / "last_sent_date.txt"
WEEKLY_SENT_FLAG_PATH: Path = DATA_DIR / "last_weekly_sent.txt"

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
ENABLE_SELENIUM_FALLBACK: bool = _get_bool("ENABLE_SELENIUM_FALLBACK", True)
DATA_SOURCE_LABEL: str = "Forex Factory"

# ---------------------------------------------------------------------------
# .ics calendar export (iPhone / Apple Calendar / Google Calendar import)
# ---------------------------------------------------------------------------
ENABLE_ICS_EXPORT: bool = _get_bool("ENABLE_ICS_EXPORT", True)

# Minutes before each event to fire the default reminder/alarm.
CALENDAR_REMINDER_MINUTES: int = int(os.getenv("CALENDAR_REMINDER_MINUTES", "15"))

# Folder (relative to project root) where generated .ics files are saved.
EXPORT_FOLDER: Path = BASE_DIR / os.getenv("EXPORT_FOLDER", "exports")
EXPORT_FOLDER.mkdir(exist_ok=True)

# Generated .ics files older than this are auto-deleted on each run.
EXPORT_FILE_MAX_AGE_HOURS: int = int(os.getenv("EXPORT_FILE_MAX_AGE_HOURS", "24"))

# ---------------------------------------------------------------------------
# GitHub Pages .ics publishing
# ---------------------------------------------------------------------------
ENABLE_GITHUB_ICS_PUBLISH: bool = _get_bool("ENABLE_GITHUB_ICS_PUBLISH", True)
GITHUB_REPO_PATH: Path = Path(
    os.getenv("GITHUB_REPO_PATH", "/Users/liphng/Downloads/forex-calendar")
).expanduser()
GITHUB_ICS_FILENAME: str = os.getenv("GITHUB_ICS_FILENAME", "calendar.ics")
CALENDAR_URL: str = os.getenv(
    "CALENDAR_URL", "https://liphng.github.io/forex-calendar/calendar.ics"
)
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
GITHUB_OWNER: str = os.getenv("GITHUB_OWNER", "liphng")
GITHUB_PAGES_REPO: str = os.getenv("GITHUB_PAGES_REPO", "forex-calendar")
GITHUB_PAGES_BRANCH: str = os.getenv("GITHUB_PAGES_BRANCH", "main")
