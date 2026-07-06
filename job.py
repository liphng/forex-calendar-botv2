"""
job.py
------
The actual "scrape -> format -> send" job that runs once per day.

Flow:
    scrape events
    -> send Telegram summary
    -> generate .ics calendar
    -> publish to GitHub Pages
    -> send subscription link

Duplicate-send protection:
writes today's date to a flag file after successful send.
"""

from __future__ import annotations

import base64
import logging
import shutil
from datetime import datetime
from pathlib import Path

import pytz
import requests

try:
    from git import Repo
    from git.exc import GitCommandError, InvalidGitRepositoryError
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    Repo = None
    GitCommandError = InvalidGitRepositoryError = Exception

import config
import scraper
import formatter
import telegram_bot
import calendar_generator

logger = logging.getLogger("job")

TARGET_TZ = pytz.timezone(config.TIMEZONE)

# ---------------------------------------------------------
# DUPLICATE SEND PROTECTION
# ---------------------------------------------------------

def already_sent_today() -> bool:
    """Check if today's summary was already sent."""
    if not config.SENT_FLAG_PATH.exists():
        return False

    today_str = datetime.now(TARGET_TZ).strftime("%Y-%m-%d")

    last_sent = config.SENT_FLAG_PATH.read_text(
        encoding="utf-8"
    ).strip()

    return last_sent == today_str


def _mark_sent_today() -> None:
    """Mark today's summary as sent."""
    today_str = datetime.now(TARGET_TZ).strftime("%Y-%m-%d")

    config.SENT_FLAG_PATH.write_text(
        today_str,
        encoding="utf-8",
    )


# ---------------------------------------------------------
# MAIN DAILY JOB
# ---------------------------------------------------------

def run_daily_job() -> bool:
    """
    Full pipeline:
        scrape
        -> filter
        -> format
        -> send Telegram summary
        -> generate/publish calendar
        -> mark sent
    """

    today_str = datetime.now(TARGET_TZ).strftime("%Y-%m-%d")

    if already_sent_today():
        logger.info(
            "Summary for %s already sent today.",
            today_str,
        )
        return True

    logger.info("Running daily job for %s", today_str)

    # -----------------------------------------------------
    # SCRAPE EVENTS
    # -----------------------------------------------------

    try:
        raw_events = scraper.get_today_events()

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Scraping failed entirely: %s",
            exc,
            exc_info=True,
        )
        raw_events = []

    scraper.save_events_json(raw_events)

    # -----------------------------------------------------
    # FILTER + FORMAT
    # -----------------------------------------------------

    filtered_events = formatter.filter_events(raw_events)

    message = formatter.build_message(
        filtered_events,
        display_date=today_str,
    )

    # -----------------------------------------------------
    # SEND TELEGRAM SUMMARY
    # -----------------------------------------------------

    sent_ok = telegram_bot.send_message_chunked(message)

    if not sent_ok:
        logger.error(
            "FAILED to send Telegram summary for %s.",
            today_str,
        )
        return False

    # -----------------------------------------------------
    # GENERATE + PUBLISH ICS
    # -----------------------------------------------------

    if config.ENABLE_ICS_EXPORT:

        ics_ok = _generate_and_publish_ics(
            filtered_events,
            today_str,
        )

        if not ics_ok:
            logger.error(
                ".ics generation/publish failed for %s",
                today_str,
            )

    # -----------------------------------------------------
    # MARK SENT
    # -----------------------------------------------------

    _mark_sent_today()

    logger.info(
        "Daily job completed successfully for %s.",
        today_str,
    )

    return True


# ---------------------------------------------------------
# ICS GENERATION + GITHUB PUBLISH
# ---------------------------------------------------------

def _generate_and_publish_ics(
    filtered_events,
    today_str: str,
) -> bool:
    """
    Generate today's .ics file and publish it to GitHub Pages.
    """

    # -----------------------------------------------------
    # CLEAN OLD EXPORTS
    # -----------------------------------------------------

    try:
        calendar_generator.cleanup_old_exports()

    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Old .ics cleanup failed: %s",
            exc,
            exc_info=True,
        )

    # -----------------------------------------------------
    # GENERATE ICS
    # -----------------------------------------------------

    try:
        ics_path = calendar_generator.build_ics(
            filtered_events,
            display_date=today_str,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error(
            ".ics generation failed: %s",
            exc,
            exc_info=True,
        )
        return False

    if ics_path is None:
        logger.info(
            "No .ics file generated for %s.",
            today_str,
        )
        return True

    # -----------------------------------------------------
    # SEND ICS TO TELEGRAM
    # -----------------------------------------------------

    caption = (
        f"Forex calendar events for {today_str}\n"
        "Tap the .ics file to import all events into your calendar."
    )

    if not telegram_bot.send_ics_document(Path(ics_path), caption):
        logger.error(
            "Generated .ics file, but Telegram document send failed for %s.",
            today_str,
        )
        return False

    if not config.ENABLE_GITHUB_ICS_PUBLISH:
        logger.info("GitHub .ics publishing disabled by ENABLE_GITHUB_ICS_PUBLISH.")
        return True

    if config.GITHUB_TOKEN:
        published = _publish_ics_via_github_api(
            Path(ics_path),
            today_str,
        )
    else:
        published = _publish_ics_via_local_repo(
            Path(ics_path),
            today_str,
        )

    if not published:
        return False

    # -----------------------------------------------------
    # SEND SUBSCRIPTION LINK
    # -----------------------------------------------------

    subscription_message = (
        f"📅 Forex calendar updated for {today_str}\n\n"
        f"Subscribe on iPhone / Apple Calendar:\n"
        f"{config.CALENDAR_URL}"
    )

    telegram_bot.send_message_chunked(
        subscription_message
    )

    return True


def _publish_ics_via_github_api(ics_path: Path, today_str: str) -> bool:
    """
    Publish calendar.ics without a local checkout. This is the Railway path:
    provide GITHUB_TOKEN with Contents read/write access.
    """
    owner = config.GITHUB_OWNER
    repo_name = config.GITHUB_PAGES_REPO
    branch = config.GITHUB_PAGES_BRANCH
    filename = config.GITHUB_ICS_FILENAME
    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{filename}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        sha = None
        get_response = requests.get(
            url,
            headers=headers,
            params={"ref": branch},
            timeout=config.REQUEST_TIMEOUT,
        )

        if get_response.status_code == 200:
            sha = get_response.json().get("sha")
        elif get_response.status_code != 404:
            logger.error(
                "GitHub API lookup failed for %s/%s:%s (%s): %s",
                owner,
                repo_name,
                filename,
                get_response.status_code,
                get_response.text,
            )
            return False

        content = base64.b64encode(ics_path.read_bytes()).decode("ascii")
        payload = {
            "message": f"Update forex calendar {today_str}",
            "content": content,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        put_response = requests.put(
            url,
            headers=headers,
            json=payload,
            timeout=config.REQUEST_TIMEOUT,
        )

        if put_response.status_code not in {200, 201}:
            logger.error(
                "GitHub API publish failed for %s/%s:%s (%s): %s",
                owner,
                repo_name,
                filename,
                put_response.status_code,
                put_response.text,
            )
            return False

        logger.info(
            "Published .ics via GitHub API to %s/%s:%s",
            owner,
            repo_name,
            filename,
        )
        return True

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "GitHub API publish failed: %s",
            exc,
            exc_info=True,
        )
        return False


def _publish_ics_via_local_repo(ics_path: Path, today_str: str) -> bool:
    """
    Publish calendar.ics through a local Git checkout. This is useful on a
    laptop/VPS, while Railway should use _publish_ics_via_github_api.
    """
    # -----------------------------------------------------
    # COPY TO GITHUB REPO
    # -----------------------------------------------------

    try:
        repo_path = config.GITHUB_REPO_PATH
        target_ics = repo_path / config.GITHUB_ICS_FILENAME

        shutil.copyfile(
            ics_path,
            target_ics,
        )

        logger.info(
            "Copied .ics into GitHub Pages repo: %s",
            target_ics,
        )

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed copying .ics into repo: %s",
            exc,
            exc_info=True,
        )
        return False

    # -----------------------------------------------------
    # GIT COMMIT + PUSH
    # -----------------------------------------------------

    try:
        if Repo is None:
            logger.error(
                "GitPython is not installed; cannot commit/push %s.",
                target_ics,
            )
            return False

        repo = Repo(repo_path)

        if repo.bare:
            logger.error("GitHub Pages repo is bare, cannot publish: %s", repo_path)
            return False

        repo.git.add(config.GITHUB_ICS_FILENAME)

        if not repo.is_dirty(index=True, working_tree=True, untracked_files=True):
            logger.info("No Git changes detected for %s; skipping commit.", target_ics)
        else:
            repo.index.commit(
                f"Update forex calendar {today_str}"
            )

            logger.info("Committed updated calendar file.")

        origin = repo.remote(name="origin")
        push_info = origin.push()

        logger.info(
            "Successfully pushed updated calendar to GitHub: %s",
            "; ".join(str(info) for info in push_info) or "ok",
        )

    except (GitCommandError, InvalidGitRepositoryError) as exc:
        logger.error(
            "GitHub commit/push failed for repo %s: %s",
            repo_path,
            exc,
            exc_info=True,
        )
        return False

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "GitHub push failed: %s",
            exc,
            exc_info=True,
        )
        return False

    return True


# ---------------------------------------------------------
# MANUAL TEST ENTRYPOINT
# ---------------------------------------------------------

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "[%(levelname)s] "
            "%(name)s: "
            "%(message)s"
        ),
    )

    run_daily_job()
