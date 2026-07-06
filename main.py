"""
main.py
-------
Application entry point.

Usage:
    python main.py            # start the 24/7 scheduler (production mode)
    python main.py --once     # run the daily job once immediately and exit (manual test)
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys

import config


def configure_logging() -> None:
    """
    Set up three rotating log files as required:
      - logs/scraper.log
      - logs/telegram.log
      - logs/scheduler.log
    plus console output for interactive/Docker use.
    """
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    def _file_handler(filename: str) -> logging.Handler:
        handler = logging.handlers.RotatingFileHandler(
            config.LOG_DIR / filename, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        handler.setFormatter(formatter)
        return handler

    logging.getLogger("scraper").addHandler(_file_handler("scraper.log"))
    logging.getLogger("telegram_bot").addHandler(_file_handler("telegram.log"))
    logging.getLogger("scheduler").addHandler(_file_handler("scheduler.log"))
    logging.getLogger("job").addHandler(_file_handler("scheduler.log"))
    logging.getLogger("formatter").addHandler(_file_handler("scheduler.log"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Forex Economic Calendar Reminder Bot")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the daily scrape+send job once immediately and exit (does not start the scheduler).",
    )
    args = parser.parse_args()

    configure_logging()
    logger = logging.getLogger("main")

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_BOT_TOKEN and/or TELEGRAM_CHAT_ID are not set. "
            "Copy .env.example to .env and fill in your credentials before running."
        )
        sys.exit(1)

    if args.once:
        logger.info("Running one-off job (--once flag set).")
        from job import run_daily_job

        success = run_daily_job()
        sys.exit(0 if success else 1)
    else:
        logger.info("Starting 24/7 scheduler...")


        import scheduler

        scheduler.main()

if __name__ == "__main__":
    main()
