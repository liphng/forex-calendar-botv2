# Forex Economic Calendar Reminder Bot

Automatically scrapes Forex economic calendar events and sends:

- a weekly outlook for the full current week
- a clean daily Telegram summary every morning at **6:00 AM GMT+08:00**

```
📅 Forex Events — 2026-07-02 (GMT+8)

🔴 HIGH IMPACT
8:30 AM — USD — Non-Farm Payrolls
Brief: Measures employment change excluding the farming industry. Major volatility driver.

9:00 AM — EUR — ECB Interest Rate Decision
Brief: Central bank's benchmark rate decision — directly moves currency valuation.

🟠 MEDIUM IMPACT
2:00 PM — GBP — Manufacturing PMI
Brief: Purchasing Managers' Index — above 50 signals expansion, below 50 signals contraction.

Data Source: Forex Factory
```

---

## 1. How data is collected (important design note)

Forex Factory's public calendar page (`forexfactory.com/calendar`) is
JavaScript-rendered and sits behind bot-detection, which makes plain HTML
scraping fragile. Instead, this project uses a two-tier strategy:

1. **Primary — JSON feed** (`scraper.py::fetch_events_from_json`): Forex
   Factory's own embeddable calendar widgets pull from a public JSON
   endpoint (`https://nfs.faireconomy.media/ff_calendar_thisweek.json`).
   This returns the same event data (title, currency, impact, date/time)
   without needing a browser, and is far more stable.
2. **Fallback — Selenium + BeautifulSoup** (`scraper.py::fetch_events_from_html`):
   If the JSON feed is ever unreachable or returns unusable data, the bot
   falls back to rendering the real calendar page with headless Chrome and
   parsing the DOM, exactly as originally specified (waits for the table to
   load, carries forward blank/repeated date & time cells, reads impact
   from icon color/title).

Both paths normalize every event to the `Asia/Singapore` (GMT+08:00)
timezone before returning.

**Compliance note:** Please review Forex Factory's Terms of Service before
running this in production. Automated scraping of some sites may be
restricted by their terms even when technically accessible — the JSON feed
here is the same one used by their own public embeddable widgets, but you
are responsible for confirming your usage complies with their current ToS.

---

## 2. Project structure

```
forex-calendar-bot/
├── main.py                     # Entry point (starts scheduler or runs once)
├── job.py                      # Core pipeline: scrape -> filter -> format -> send -> .ics
├── scraper.py                  # JSON + Selenium/BeautifulSoup scraping logic
├── formatter.py                # Message building + reusable event-summary mapping
├── telegram_bot.py             # Telegram send logic (text + .ics document) with retries
├── calendar_generator.py       # Builds the daily .ics file (Apple/Google Calendar import)
├── bot_listener.py             # Answers taps on the "Add All Events to iPhone" button
├── scheduler.py                # APScheduler cron job (06:00 GMT+8, persists across restarts)
├── config.py                   # All settings, loaded from .env
├── requirements.txt
├── .env.example                # Copy to .env and fill in
├── Dockerfile
├── docker-compose.yml
├── forex-calendar-bot.service  # systemd unit
├── run_once_cron.sh            # plain-cron alternative to scheduler.py
├── data/                       # events_today.json, events_week.json, sent flags, jobs.sqlite
├── exports/                    # daily forex_events_YYYY-MM-DD.ics files (auto-cleaned after 24h)
└── logs/                       # scraper.log, telegram.log, scheduler.log
```

---

## 3. Quick start (local / VPS)

```bash
git clone <this-repo>
cd forex-calendar-bot

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
nano .env          # fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

# Send yourself today's summary right now, as a test:
python main.py --once

# Start the 24/7 scheduler (blocks the terminal — use systemd/Docker for production):
python main.py
```

If you enabled the Selenium fallback (`ENABLE_SELENIUM_FALLBACK=true`, the
default) and it ever gets exercised, you'll also need Chrome/Chromium and a
matching chromedriver on the host. `webdriver-manager` (already in
`requirements.txt`) will download the correct driver automatically the
first time it's needed. On Docker, the provided `Dockerfile` already
installs Google Chrome for you.

---

## 4. Telegram Bot creation guide (BotFather)

1. Open Telegram and search for **`@BotFather`**.
2. Send `/newbot`.
3. Choose a display name (e.g. `My Forex Calendar Bot`).
4. Choose a unique username ending in `bot` (e.g. `myforexcalendar_bot`).
5. BotFather replies with your **bot token** — looks like
   `123456789:AAExampleTokenReplaceMe`. Put this in `.env` as
   `TELEGRAM_BOT_TOKEN`.
6. Get your **chat ID**:
   - Easiest: message **`@userinfobot`** on Telegram — it replies with your
     numeric user ID. Use that as `TELEGRAM_CHAT_ID` for a DM to yourself.
   - For a group: add your new bot to the group, send any message in the
     group, then visit
     `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser —
     look for `"chat":{"id": -100...}` in the JSON response.
7. Send your bot a `/start` message first (Telegram requires the user to
   initiate contact with a bot before it can message them).
8. Test it: `python main.py --once`.

---

## 5. Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Required. From BotFather. |
| `TELEGRAM_CHAT_ID` | — | Required. Target chat/user/group ID. |
| `TIMEZONE` | `Asia/Singapore` | GMT+08:00, no DST. |
| `SEND_HOUR` / `SEND_MINUTE` | `6` / `0` | Daily send time in `TIMEZONE`. |
| `ENABLE_WEEKLY_UPDATE` | `true` | Send a weekly outlook in addition to the daily message. |
| `WEEKLY_SEND_DAY` | `0` | Weekly outlook day: Monday is `0`, Sunday is `6`. |
| `WEEKLY_SEND_HOUR` / `WEEKLY_SEND_MINUTE` | daily send time | Weekly outlook send time in `TIMEZONE`. |
| `FF_JSON_URL` | Forex Factory JSON feed | Primary data source. |
| `FF_CALENDAR_URL` | forexfactory.com/calendar | Fallback scrape target. |
| `ENABLE_SELENIUM_FALLBACK` | `true` | Set `false` to disable the HTML fallback entirely. |
| `IMPACT_FILTER` | `HIGH,MEDIUM` | Comma list: `HIGH`, `MEDIUM`, `LOW`. |
| `CURRENCY_FILTER` | `USD,EUR,GBP,JPY,AUD,CAD,CHF,NZD` | Comma list of currency codes to include. |
| `MAX_RETRIES` / `RETRY_BACKOFF_SECONDS` | `3` / `5` | Retry behavior for both scraping and Telegram sends. |
| `ENABLE_ICS_EXPORT` | `true` | Set `false` to disable the daily `.ics` file + button entirely. |
| `CALENDAR_REMINDER_MINUTES` | `15` | Minutes-before-event alarm baked into each calendar event. |
| `EXPORT_FOLDER` | `exports` | Folder where daily `.ics` files are saved. |
| `EXPORT_FILE_MAX_AGE_HOURS` | `24` | `.ics` files older than this are auto-deleted on each run. |
| `ENABLE_GITHUB_ICS_PUBLISH` | `true` | Copy/commit/push the latest `.ics` file to a GitHub Pages repo. |
| `GITHUB_REPO_PATH` | `/Users/liphng/Downloads/forex-calendar` | Local checkout of the GitHub Pages repo. |
| `GITHUB_ICS_FILENAME` | `calendar.ics` | File name to publish in the GitHub Pages repo. |
| `CALENDAR_URL` | `https://liphng.github.io/forex-calendar/calendar.ics` | Public subscription URL sent after publish. |
| `GITHUB_TOKEN` | — | Railway/VPS token for publishing `calendar.ics` through the GitHub API. Needs Contents read/write access to the Pages repo. |
| `GITHUB_OWNER` | `liphng` | GitHub owner for the Pages repo. |
| `GITHUB_PAGES_REPO` | `forex-calendar` | GitHub Pages repo that hosts `calendar.ics`. |
| `GITHUB_PAGES_BRANCH` | `main` | Branch to update in the Pages repo. |

Edit `IMPACT_FILTER` / `CURRENCY_FILTER` directly in `.env` — no code
changes needed.

---

## 6. Docker deployment

```bash
cp .env.example .env   # fill in your credentials
docker compose up -d --build
docker compose logs -f
```

The container installs headless Google Chrome so the Selenium fallback
works out of the box. `data/` and `logs/` are bind-mounted so the
duplicate-send flag, job store, and log files survive container
restarts/rebuilds.

To run a one-off test send inside the container:

```bash
docker compose run --rm forex-calendar-bot python main.py --once
```

---

## 7. Ubuntu VPS deployment (systemd)

```bash
# As root or with sudo:
sudo useradd -r -s /bin/false forexbot
sudo mkdir -p /opt/forex-calendar-bot
sudo cp -r . /opt/forex-calendar-bot
cd /opt/forex-calendar-bot

sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt

sudo cp .env.example .env
sudo nano .env   # fill in credentials

sudo chown -R forexbot:forexbot /opt/forex-calendar-bot

sudo cp forex-calendar-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable forex-calendar-bot
sudo systemctl start forex-calendar-bot

# Check status / logs:
sudo systemctl status forex-calendar-bot
journalctl -u forex-calendar-bot -f
```

`Restart=always` in the unit file means systemd will restart the process
automatically if it ever crashes — the daily job's duplicate-send flag file
(`data/last_sent_date.txt`) plus the catch-up check in `scheduler.py`
ensure you still get exactly one message per day even across restarts.

---

## 8. Cron alternative

If you'd rather not run a long-lived process at all, use plain cron with
`run_once_cron.sh` instead of `scheduler.py`:

```bash
chmod +x run_once_cron.sh
crontab -e
```

Add:

```
TZ=Asia/Singapore
0 6 * * * /opt/forex-calendar-bot/run_once_cron.sh >> /opt/forex-calendar-bot/logs/cron.log 2>&1
```

`job.py`'s on-disk flag file still prevents duplicate sends even if cron
fires more than once.

---

## 9. Railway / Render deployment

Both platforms can build directly from the included `Dockerfile`.

**Railway:**
1. Create a new project → "Deploy from GitHub repo".
2. Railway auto-detects the `Dockerfile`.
3. Add environment variables from `.env.example` in the Railway dashboard
   (Variables tab) instead of committing a `.env` file.
4. For GitHub Pages calendar publishing on Railway, set `GITHUB_TOKEN`,
   `GITHUB_OWNER`, `GITHUB_PAGES_REPO`, and `GITHUB_PAGES_BRANCH`. The token
   should be a fine-grained GitHub token with **Contents: Read and write**
   permission on the Pages repo.
5. Deploy. Railway keeps the process alive continuously — no extra config
   needed for the 24/7 scheduler.

**Render:**
1. New → "Background Worker" (not "Web Service" — this bot has no HTTP
   port to bind).
2. Connect your repo; Render will build the `Dockerfile`.
3. Add the same environment variables in the Render dashboard.
4. Deploy. Render restarts the worker automatically on crash.

---

## 10. Logging

Three rotating log files are written to `logs/` (5 MB per file, 5 backups):

- `logs/scraper.log` — scraping attempts, retries, fallback triggers
- `logs/telegram.log` — send attempts, retries, failures
- `logs/scheduler.log` — job scheduling, catch-up runs, duplicate-send skips

Console output (stdout) mirrors all of the above, which is what you'll see
in `docker compose logs` or `journalctl`.

---

## 11. How to import forex events into iPhone

Every day, right after the text summary, the bot also sends a `.ics`
calendar file (`forex_events_YYYY-MM-DD.ics`) containing **all** of that
day's (filtered) events, each with a reminder alarm already attached, plus
an inline **"📅 Add All Events to iPhone"** button underneath it.

**To import everything in one tap:**

1. Open Telegram on your iPhone.
2. Scroll to the message with the `.ics` file attachment (just below the
   text summary) and **tap the file itself**.
3. iOS shows a native "Add All" preview listing every event in the file —
   tap **"Add All"**.
4. All of today's forex events are instantly added to **Apple Calendar**,
   each with its own **15-minute-before reminder** (configurable — see
   `CALENDAR_REMINDER_MINUTES` in `.env`).
5. Because they're now real Calendar events, iOS handles notifications and
   **lock-screen alerts** automatically at each event's reminder time — no
   extra setup needed.

**A quick honesty note on the inline button:** iOS's "Add All" action is
triggered natively by tapping the *file itself* — no bot, on any platform,
can trigger that action remotely on your behalf; it's handled entirely by
iOS's own document preview. The **"📅 Add All Events to iPhone"** button is
there as a one-tap helper: tapping it replies with a short, clear reminder
of exactly which file to tap and what to tap next, so if you're not sure
what to do, tapping the button walks you straight to the two-tap import.

**Using Android or Google Calendar instead?** Tap the same `.ics` file and
choose "Open with Google Calendar" (or your calendar app's own "Import"
option) — the file works there too.

**Note on running the button:** answering the button tap requires the bot
to also *receive* Telegram updates (not just send them), so `main.py`
starts a small background listener (`bot_listener.py`) alongside the
scheduler automatically whenever `ENABLE_ICS_EXPORT=true`. If you run the
daily job via the plain-cron script (`run_once_cron.sh`) instead of
`python main.py`, the `.ics` file and button will still be sent correctly,
but no process will be listening for button taps — the file itself still
works via "Add All" either way, so this only affects the extra help text.

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Bot never sends anything | You didn't message your bot first — Telegram requires the user to `/start` a bot before it can DM them. |
| `TELEGRAM_CHAT_ID is not set` error | `.env` wasn't loaded — confirm the file is named exactly `.env` and sits next to `main.py`. |
| "No high/medium impact events" every day | Check `IMPACT_FILTER`/`CURRENCY_FILTER` in `.env` aren't too restrictive; also check `data/events_today.json` to see raw scraped data before filtering. |
| JSON feed request fails (timeout/403) | Network/firewall issue, or Forex Factory temporarily changed the feed. Fallback should kick in automatically if `ENABLE_SELENIUM_FALLBACK=true`; check `logs/scraper.log`. |
| Selenium fallback fails with "chromedriver not found" | Run inside the provided Docker image (Chrome pre-installed), or install Chrome + let `webdriver-manager` fetch the driver on first run. |
| Message sent twice in one day | Shouldn't happen — `data/last_sent_date.txt` guards this. If it does, check that `data/` is actually persisted (not wiped) between runs. |
| Wrong send time | Confirm `TIMEZONE=Asia/Singapore` in `.env` and that the host's Python/pytz timezone database is up to date. |
| Times look shifted from what you expect on the FF website | The JSON feed's timestamps are converted from US/Eastern → your target timezone; if FF changes their feed's offset behavior, cross-check `data/events_today.json` against the live site. |

---

## 13. Future improvements

- Add Playwright as an additional fallback engine (scaffolded for, not yet
  wired in — see the commented line in `requirements.txt`).
- Add a `/today` and `/tomorrow` Telegram command for on-demand summaries
  instead of only the scheduled push.
- Persist historical events to a proper database (SQLite/Postgres) for
  backtesting "event → market reaction" analysis.
- Support multiple Telegram chat IDs (e.g. broadcast to a channel + a
  personal DM).
- Replace the keyword-based event-summary mapping in `formatter.py` with an
  LLM call for more nuanced, context-aware summaries.
- Add a lightweight healthcheck HTTP endpoint for platforms (like Render's
  Web Service tier) that require one.

---

## 14. Example message output

See the example at the top of this README, and `data/events_today.json`
after any run for the raw structured data behind it:

```json
[
  {
    "date": "2026-07-02",
    "time": "08:30",
    "currency": "USD",
    "impact": "High",
    "event": "Non-Farm Payrolls"
  }
]
```
