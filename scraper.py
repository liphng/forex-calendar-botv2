"""
scraper.py
----------
Collects economic calendar events for the CURRENT DAY (in the configured
timezone, default GMT+08:00).

Strategy (in order):
  1. PRIMARY:  Fetch Forex Factory's public JSON feed (ff_calendar_thisweek.json).
               This is the same data source used by Forex Factory's own
               embeddable calendar widgets, so it does not require a browser
               and is not subject to Cloudflare/anti-bot JS challenges.
  2. FALLBACK: If the JSON feed fails or returns invalid data, fall back to
               rendering https://www.forexfactory.com/calendar with Selenium
               (headless Chrome) and parsing the DOM with BeautifulSoup.

All timestamps are normalized to the configured timezone (Asia/Singapore,
GMT+08:00) before being returned.

Every event dict returned has the shape:
{
    "date": "2026-07-02",      # YYYY-MM-DD in target timezone
    "time": "08:30",           # HH:MM 24h in target timezone, "" if all-day/tentative
    "currency": "USD",
    "impact": "High",          # High | Medium | Low | Holiday | Unknown
    "event": "Non-Farm Payrolls",
}
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, date
from typing import List, Dict, Any, Optional

import pytz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger("scraper")

TARGET_TZ = pytz.timezone(config.TIMEZONE)

IMPACT_MAP = {
    # ff_calendar_thisweek.json uses these labels/colors
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "holiday": "Holiday",
    "non-economic": "Low",
}


def _build_session() -> requests.Session:
    """Build a requests Session with retry logic and realistic headers."""
    session = requests.Session()
    retries = Retry(
        total=config.MAX_RETRIES,
        backoff_factor=config.RETRY_BACKOFF_SECONDS,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.forexfactory.com/calendar",
            "Connection": "keep-alive",
        }
    )
    return session


def _normalize_impact(raw_impact: str) -> str:
    if not raw_impact:
        return "Unknown"
    key = raw_impact.strip().lower()
    return IMPACT_MAP.get(key, "Unknown")


def _parse_ff_json_datetime(raw_date: str) -> Optional[datetime]:
    """
    ff_calendar_thisweek.json timestamps come as an ISO-8601 string, e.g.
    '2026-07-02T08:30:00-04:00' (source timezone is US Eastern).
    Convert to an aware datetime, then to the target timezone.
    """
    if not raw_date:
        return None
    try:
        dt = datetime.fromisoformat(raw_date)
        if dt.tzinfo is None:
            # Assume US/Eastern if no offset is present (Forex Factory's
            # server timezone) rather than silently treating it as naive UTC.
            eastern = pytz.timezone("America/New_York")
            dt = eastern.localize(dt)
        return dt.astimezone(TARGET_TZ)
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse datetime %r: %s", raw_date, exc)
        return None


def fetch_events_from_json(today: date) -> List[Dict[str, Any]]:
    """
    PRIMARY scraping path: pull the week's events from Forex Factory's public
    JSON feed and filter down to `today` in the target timezone.
    """
    session = _build_session()
    logger.info("Fetching calendar JSON from %s", config.FF_JSON_URL)

    response = session.get(config.FF_JSON_URL, timeout=config.REQUEST_TIMEOUT)
    response.raise_for_status()

    raw_events = response.json()
    if not isinstance(raw_events, list):
        raise ValueError("Unexpected JSON payload shape (expected a list)")

    events: List[Dict[str, Any]] = []
    for item in raw_events:
        # Typical keys in this feed: title, country, date, impact, forecast,
        # previous. Field names have varied slightly over time, so we probe
        # a few possibilities defensively.
        title = item.get("title") or item.get("event") or ""
        currency = (item.get("country") or item.get("currency") or "").upper()
        raw_impact = item.get("impact", "")
        raw_date = item.get("date", "")

        dt_local = _parse_ff_json_datetime(raw_date)
        if dt_local is None:
            logger.debug("Skipping event with unparseable date: %r", item)
            continue

        if dt_local.date() != today:
            continue

        events.append(
            {
                "date": dt_local.strftime("%Y-%m-%d"),
                "time": dt_local.strftime("%H:%M"),
                "currency": currency or "N/A",
                "impact": _normalize_impact(raw_impact),
                "event": title.strip() or "Unnamed Event",
            }
        )

    logger.info("JSON feed returned %d event(s) for %s", len(events), today)
    return events


# ---------------------------------------------------------------------------
# FALLBACK: Selenium + BeautifulSoup HTML scraping
# ---------------------------------------------------------------------------
def fetch_events_from_html(today: date) -> List[Dict[str, Any]]:
    """
    FALLBACK scraping path: render the Forex Factory calendar page with
    headless Selenium (Chrome) and parse rows with BeautifulSoup.

    Forex Factory's calendar table repeats/blanks the date and time cells for
    consecutive rows belonging to the same date/time, so we carry forward the
    last-seen date/time values ("row-span" style parsing).

    NOTE: This path depends on Forex Factory's current HTML structure and on
    a Chrome/Chromedriver binary being available in the runtime environment.
    It exists as a robustness fallback per project requirements; the JSON
    feed in fetch_events_from_json() should be preferred whenever available.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from bs4 import BeautifulSoup

    logger.info("Falling back to Selenium HTML scrape of %s", config.FF_CALENDAR_URL)

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(f"user-agent={config.USER_AGENT}")
    # Reduce obvious automation fingerprints.
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    events: List[Dict[str, Any]] = []

    try:
        driver.get(config.FF_CALENDAR_URL)

        # Wait for the calendar table to actually load (dynamic content).
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "table.calendar__table"))
        )
        # Small grace period for JS-rendered rows to finish populating.
        time.sleep(2)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        table = soup.select_one("table.calendar__table")
        if table is None:
            raise ValueError("Calendar table not found in rendered HTML")

        current_date_str: Optional[str] = None
        current_time_str: str = ""

        for row in table.select("tr.calendar__row"):
            # Date cell only appears on the first row of a new day.
            date_cell = row.select_one("td.calendar__cell.calendar__date")
            if date_cell and date_cell.get_text(strip=True):
                current_date_str = date_cell.get_text(strip=True)

            # Time cell is blank for consecutive events at the same time.
            time_cell = row.select_one("td.calendar__cell.calendar__time")
            if time_cell:
                text = time_cell.get_text(strip=True)
                if text:
                    current_time_str = text

            currency_cell = row.select_one("td.calendar__cell.calendar__currency")
            impact_cell = row.select_one("td.calendar__cell.calendar__impact span")
            event_cell = row.select_one("td.calendar__cell.calendar__event")

            if not (currency_cell and event_cell):
                # Not a real event row (could be a spacer/header row).
                continue

            currency = currency_cell.get_text(strip=True).upper()
            event_title = event_cell.get_text(strip=True)

            impact_label = "Unknown"
            if impact_cell and impact_cell.has_attr("title"):
                impact_label = impact_cell["title"].replace(" Impact Expected", "")
            elif impact_cell and impact_cell.has_attr("class"):
                classes = " ".join(impact_cell["class"])
                if "high" in classes:
                    impact_label = "High"
                elif "medium" in classes or "orange" in classes:
                    impact_label = "Medium"
                elif "low" in classes or "yellow" in classes:
                    impact_label = "Low"

            if not current_date_str or not event_title:
                continue

            parsed_dt = _parse_html_row_datetime(current_date_str, current_time_str, today.year)
            if parsed_dt is None or parsed_dt.date() != today:
                continue

            events.append(
                {
                    "date": parsed_dt.strftime("%Y-%m-%d"),
                    "time": parsed_dt.strftime("%H:%M") if current_time_str else "",
                    "currency": currency or "N/A",
                    "impact": _normalize_impact(impact_label),
                    "event": event_title,
                }
            )

    finally:
        driver.quit()

    logger.info("HTML fallback scrape returned %d event(s) for %s", len(events), today)
    return events


def _parse_html_row_datetime(date_str: str, time_str: str, year: int) -> Optional[datetime]:
    """
    Parse Forex Factory's HTML date/time text (e.g. 'JulΓÇÇ2' + '8:30am')
    into a timezone-aware datetime in the target timezone. Handles all-day /
    tentative rows where time_str may be empty, "All Day", or "Tentative".
    """
    date_str = date_str.replace("\u2013", "-").strip()
    try:
        # Example date_str formats seen on FF: "Jul 2", "JulΓÇÇ2" (encoding
        # artifact for a non-breaking space), "Wed Jul 2".
        cleaned = "".join(ch for ch in date_str if ch.isalnum() or ch.isspace())
        parts = cleaned.split()
        # Keep only month + day tokens (drop weekday if present).
        month_day = [p for p in parts if not p.isalpha() or len(p) == 3]
        month_day_str = " ".join(month_day[-2:]) if len(month_day) >= 2 else cleaned
        naive_date = datetime.strptime(f"{month_day_str} {year}", "%b %d %Y")
    except ValueError:
        logger.debug("Could not parse date string: %r", date_str)
        return None

    time_str_clean = (time_str or "").strip().lower()
    if time_str_clean in {"", "all day", "tentative", "n/a"}:
        naive_dt = naive_date  # midnight placeholder for all-day events
    else:
        try:
            naive_time = datetime.strptime(time_str_clean, "%I:%M%p")
            naive_dt = naive_date.replace(hour=naive_time.hour, minute=naive_time.minute)
        except ValueError:
            logger.debug("Could not parse time string: %r", time_str)
            naive_dt = naive_date

    # Forex Factory's website displays times in the visitor's browser/session
    # timezone; when scraped headlessly this is typically US/Eastern by
    # default. We localize as Eastern then convert to the target timezone,
    # mirroring the JSON path for consistency.
    eastern = pytz.timezone("America/New_York")
    localized = eastern.localize(naive_dt)
    return localized.astimezone(TARGET_TZ)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def get_today_events() -> List[Dict[str, Any]]:
    """
    Return today's (in target timezone) economic calendar events, trying the
    JSON feed first and falling back to HTML scraping on failure.
    """
    today = datetime.now(TARGET_TZ).date()

    try:
        events = fetch_events_from_json(today)
        if events:
            return _dedupe(events)
        logger.warning("JSON feed returned zero events for today; trying fallback")
    except Exception as exc:  # noqa: BLE001 - we want to fall back on any failure
        logger.error("Primary JSON scrape failed: %s", exc, exc_info=True)

    if not config.ENABLE_SELENIUM_FALLBACK:
        logger.warning("Selenium fallback disabled; returning empty event list")
        return []

    try:
        events = fetch_events_from_html(today)
        return _dedupe(events)
    except Exception as exc:  # noqa: BLE001
        logger.error("Fallback HTML scrape failed: %s", exc, exc_info=True)
        return []


def _dedupe(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove exact duplicate event rows (can happen with feed quirks)."""
    seen = set()
    unique = []
    for ev in events:
        key = (ev["date"], ev["time"], ev["currency"], ev["event"])
        if key not in seen:
            seen.add(key)
            unique.append(ev)
    return unique


def save_events_json(events: List[Dict[str, Any]]) -> None:
    """Persist today's events to disk as JSON (for auditing / debugging)."""
    with open(config.EVENTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    logger.info("Saved %d event(s) to %s", len(events), config.EVENTS_JSON_PATH)
