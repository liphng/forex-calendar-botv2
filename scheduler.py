"""
scheduler.py
------------
Schedules the daily job at 06:00 Asia/Singapore (GMT+08:00) using APScheduler
with a persistent SQLite job store, so the schedule survives process/host
restarts (APScheduler reloads the job's next run time from disk on startup;
we additionally guard against duplicate same-day sends with an on-disk flag,
which also protects against a restart landing after 6 AM on the same day).
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

import config
from job import run_daily_job

logger = logging.getLogger("scheduler")

JOBSTORE_PATH = config.DATA_DIR / "jobs.sqlite"


def build_scheduler() -> BlockingScheduler:
    tz = pytz.timezone(config.TIMEZONE)

    jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{JOBSTORE_PATH}")}
    scheduler = BlockingScheduler(jobstores=jobstores, timezone=tz)

    trigger = CronTrigger(
        hour=config.SEND_HOUR,
        minute=config.SEND_MINUTE,
        timezone=tz,
    )

    scheduler.add_job(
        run_daily_job,
        trigger=trigger,
        id="daily_forex_summary",
        name="Daily Forex Economic Calendar Summary",
        replace_existing=True,
        misfire_grace_time=60 * 60,  # tolerate up to 1hr delay (e.g. host was asleep)
    )

    return scheduler


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(
        "Starting scheduler. Daily job set for %02d:%02d %s.",
        config.SEND_HOUR,
        config.SEND_MINUTE,
        config.TIMEZONE,
    )

    # Run an immediate catch-up check: if today's message hasn't been sent yet
    # and it's already past the scheduled time (e.g. the process restarted
    # at 6:15 AM after a crash), send it now instead of waiting a full day.
    _maybe_catch_up()

    scheduler = build_scheduler()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


def _maybe_catch_up() -> None:
    tz = pytz.timezone(config.TIMEZONE)
    now = datetime.now(tz)
    scheduled_today = now.replace(hour=config.SEND_HOUR, minute=config.SEND_MINUTE, second=0, microsecond=0)

    if now < scheduled_today:
        return  # scheduled time hasn't happened yet today; normal cron will fire it

    from job import already_sent_today  # local import to avoid circulars at module load

    if not already_sent_today():
        logger.info("Missed today's scheduled send (process likely restarted late); running catch-up now.")
        run_daily_job()
    else:
        logger.info("Today's summary was already sent; skipping catch-up.")


if __name__ == "__main__":
    main()
