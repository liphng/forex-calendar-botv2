"""
calendar_generator.py
----------------------
Builds an Apple Calendar / Google Calendar-compatible `.ics` file containing
every scraped forex event for the day, each with a VALARM reminder, so the
whole day's events can be imported to a phone's calendar in one tap.

Uses the `icalendar` library (RFC 5545 compliant), which produces files that
open correctly in the iOS "Add to Calendar" / "Add All" preview inside the
Telegram app, and also import cleanly into Google Calendar.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

import pytz
from icalendar import Calendar, Event, Alarm, vText, Timezone, TimezoneStandard

import config

logger = logging.getLogger("calendar_generator")

TARGET_TZ = pytz.timezone(config.TIMEZONE)

IMPACT_EMOJI = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟢",
    "Holiday": "⚪",
    "Unknown": "⚪",
}

# Default duration assigned to each calendar event (economic releases are
# effectively instantaneous, but a 0-minute event renders oddly in some
# calendar apps, so we give it a short, visible block).
EVENT_DURATION_MINUTES = 30

# Events with no specific time ("All Day" / holidays) get anchored here.
ALL_DAY_DEFAULT_HOUR = 8
ALL_DAY_DEFAULT_MINUTE = 0


def _event_start_datetime(event: Dict[str, Any]) -> datetime:
    """
    Build a timezone-aware datetime (Asia/Singapore) for a scraped event
    dict. Falls back to a default morning time for all-day/tentative events
    that have no specific "time" value.
    """
    date_str = event.get("date", "")
    time_str = event.get("time", "")

    try:
        base_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning("Invalid date %r on event %r; skipping datetime build", date_str, event)
        base_date = datetime.now(TARGET_TZ).replace(tzinfo=None)

    if time_str:
        try:
            hour, minute = (int(part) for part in time_str.split(":"))
        except ValueError:
            hour, minute = ALL_DAY_DEFAULT_HOUR, ALL_DAY_DEFAULT_MINUTE
    else:
        hour, minute = ALL_DAY_DEFAULT_HOUR, ALL_DAY_DEFAULT_MINUTE

    naive_dt = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return TARGET_TZ.localize(naive_dt)


def _build_summary(event: Dict[str, Any]) -> str:
    """e.g. '🔴 [USD] Non-Farm Payrolls'"""
    impact = event.get("impact", "Unknown")
    emoji = IMPACT_EMOJI.get(impact, "⚪")
    currency = event.get("currency", "N/A")
    title = event.get("event", "Unnamed Event")
    return f"{emoji} [{currency}] {title}"


def _build_description(event: Dict[str, Any], explanation: str) -> str:
    """
    Multi-line description as specified:

        Currency: USD
        Impact: High
        Time: 08:30 AM GMT+8

        Explanation:
        <short summary>

        Source:
        Forex Factory
    """
    time_str = event.get("time", "")
    if time_str:
        try:
            display_time = datetime.strptime(time_str, "%H:%M").strftime("%I:%M %p").lstrip("0")
        except ValueError:
            display_time = time_str
    else:
        display_time = "All Day"

    lines = [
        f"Currency: {event.get('currency', 'N/A')}",
        f"Impact: {event.get('impact', 'Unknown')}",
        f"Time: {display_time} GMT+8",
        "",
        "Explanation:",
        explanation,
        "",
        "Source:",
        config.DATA_SOURCE_LABEL,
    ]
    return "\n".join(lines)


def _build_vtimezone() -> Timezone:
    """
    Explicit VTIMEZONE block for Asia/Singapore (fixed UTC+08:00, no DST).

    Most modern clients (Apple Calendar, Google Calendar) recognize bare
    IANA TZIDs like "Asia/Singapore" even without this, but RFC 5545
    recommends including a VTIMEZONE definition for any TZID referenced by
    an event, and embedding it removes any ambiguity for stricter/older
    calendar parsers on iOS.
    """
    tz_component = Timezone()
    tz_component.add("tzid", config.TIMEZONE)

    standard = TimezoneStandard()
    standard.add("dtstart", datetime(1970, 1, 1, 0, 0, 0))
    standard.add("tzoffsetfrom", timedelta(hours=8))
    standard.add("tzoffsetto", timedelta(hours=8))
    standard.add("tzname", "+08")

    tz_component.add_component(standard)
    return tz_component


def build_ics(
    events: List[Dict[str, Any]],
    display_date: str,
    reminder_minutes: Optional[int] = None,
) -> Optional[Path]:
    """
    Build an .ics file for `events` (already filtered/sorted as desired) and
    save it to config.EXPORT_FOLDER. Returns the file Path, or None if there
    were no events to include.

    Each VEVENT gets:
      - SUMMARY: "<impact emoji> [<currency>] <event title>"
      - DESCRIPTION: currency / impact / time / explanation / source
      - DTSTART/DTEND localized to Asia/Singapore (GMT+08:00)
      - One VALARM reminder, `reminder_minutes` before the event start
        (defaults to config.CALENDAR_REMINDER_MINUTES)
    """
    # Local import avoids a hard dependency for callers that only need the
    # dataclass-free parts of this module (keeps formatter.py decoupled).
    from formatter import get_event_summary

    if not events:
        logger.info("No events to include in .ics export for %s; skipping file generation.", display_date)
        return None

    minutes_before = reminder_minutes if reminder_minutes is not None else config.CALENDAR_REMINDER_MINUTES

    cal = Calendar()
    cal.add("prodid", "-//Forex Calendar Reminder Bot//forexfactory-telegram-bot//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", vText(f"Forex Events — {display_date}"))
    cal.add("x-wr-timezone", vText(config.TIMEZONE))
    cal.add_component(_build_vtimezone())

    for idx, event in enumerate(events):
        start_dt = _event_start_datetime(event)
        end_dt = start_dt + timedelta(minutes=EVENT_DURATION_MINUTES)
        explanation = get_event_summary(event.get("event", ""))

        vevent = Event()
        vevent.add("summary", vText(_build_summary(event)))
        vevent.add("description", vText(_build_description(event, explanation)))
        vevent.add("dtstart", start_dt)
        vevent.add("dtend", end_dt)
        vevent.add("dtstamp", datetime.now(pytz.utc))
        vevent.add(
            "uid",
            f"forex-{event.get('date')}-{event.get('time') or 'allday'}-"
            f"{event.get('currency')}-{idx}@forex-calendar-bot",
        )
        vevent.add("location", vText(config.DATA_SOURCE_LABEL))
        vevent.add("categories", vText("Forex,Economic Calendar"))

        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", vText(f"Reminder: {_build_summary(event)}"))
        alarm.add("trigger", timedelta(minutes=-minutes_before))
        vevent.add_component(alarm)

        cal.add_component(vevent)

    filename = f"forex_events_{display_date}.ics"
    filepath = config.EXPORT_FOLDER / filename

    try:
        with open(filepath, "wb") as f:
            f.write(cal.to_ical())
    except OSError as exc:
        logger.error("Failed to write .ics file to %s: %s", filepath, exc, exc_info=True)
        return None

    logger.info("Generated .ics file with %d event(s): %s", len(events), filepath)
    return filepath


def cleanup_old_exports(max_age_hours: Optional[int] = None) -> int:
    """
    Delete previously generated .ics files older than `max_age_hours`
    (defaults to config.EXPORT_FILE_MAX_AGE_HOURS). Returns the number of
    files deleted. Safe to call on every run.
    """
    max_age = max_age_hours if max_age_hours is not None else config.EXPORT_FILE_MAX_AGE_HOURS
    cutoff = time.time() - (max_age * 3600)
    deleted = 0

    if not config.EXPORT_FOLDER.exists():
        return 0

    for f in config.EXPORT_FOLDER.glob("forex_events_*.ics"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
                logger.info("Deleted stale export file: %s", f)
        except OSError as exc:
            logger.warning("Could not delete stale export file %s: %s", f, exc)

    if deleted:
        logger.info("Cleanup removed %d stale .ics file(s).", deleted)
    return deleted
