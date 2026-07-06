#!/usr/bin/env bash
#
# run_once_cron.sh
# -----------------
# Alternative to the built-in APScheduler-based scheduler.py, for environments
# that prefer plain system cron.
#
# This script runs the daily job exactly once and exits (job.py's own
# already-sent-today flag file still protects against duplicate sends, so
# it's safe even if cron fires this more than once on the same day).
#
# Example crontab entry (crontab -e), assuming the VPS's system timezone is
# already set to Asia/Singapore (GMT+08:00):
#
#   0 6 * * * /opt/forex-calendar-bot/run_once_cron.sh >> /opt/forex-calendar-bot/logs/cron.log 2>&1
#
# If your VPS is NOT on Asia/Singapore time, either:
#   a) set the system timezone:  sudo timedatectl set-timezone Asia/Singapore
#   b) or use TZ= in the crontab line, e.g.:
#      TZ=Asia/Singapore
#      0 6 * * * /opt/forex-calendar-bot/run_once_cron.sh >> ... 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtualenv if present
if [ -f "venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source venv/bin/activate
fi

python3 main.py --once
