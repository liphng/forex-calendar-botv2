"""
formatter.py
------------
Turns raw scraped event dicts into a clean, emoji-formatted Telegram message.

Includes a reusable "event-summary mapping system": a keyword-based lookup
that generates a short, plain-English explanation of what each economic
event measures (e.g. NFP -> employment strength, CPI -> inflation).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Any

import config

logger = logging.getLogger("formatter")

IMPACT_EMOJI = {
    "High": "🔴",
    "Medium": "🟠",
    "Low": "🟢",
    "Holiday": "⚪",
    "Unknown": "⚪",
}

IMPACT_HEADER = {
    "High": "🔴 HIGH IMPACT",
    "Medium": "🟠 MEDIUM IMPACT",
    "Low": "🟢 LOW IMPACT",
}

IMPACT_ORDER = ["High", "Medium", "Low"]


# ---------------------------------------------------------------------------
# Reusable event-summary mapping system
# ---------------------------------------------------------------------------
# Keys are matched case-insensitively as substrings against the event title,
# checked in order, first match wins. This makes it trivial to extend: just
# append a new (keyword, explanation) pair.
EVENT_SUMMARY_RULES: List[tuple] = [
    ("non-farm payroll", "Measures employment change excluding the farming industry. Major volatility driver."),
    ("nfp", "Measures employment change excluding the farming industry. Major volatility driver."),
    ("unemployment rate", "Share of the workforce currently without a job. Key labor market health gauge."),
    ("employment change", "Net change in the number of employed people over the period."),
    ("average earnings", "Tracks wage growth, an input into inflation expectations."),
    ("cpi", "Consumer Price Index — a key inflation indicator tracking price changes for goods/services."),
    ("core cpi", "Inflation reading excluding volatile food & energy prices."),
    ("ppi", "Producer Price Index — measures wholesale price inflation before it reaches consumers."),
    ("inflation", "Tracks the rate of price increases across the economy."),
    ("interest rate decision", "Central bank's benchmark rate decision — directly moves currency valuation."),
    ("rate decision", "Central bank's benchmark rate decision — directly moves currency valuation."),
    ("fomc", "Federal Reserve policy meeting outcome/minutes — high-impact USD driver."),
    ("monetary policy statement", "Central bank's forward guidance on interest rates and economic outlook."),
    ("pmi", "Purchasing Managers' Index — above 50 signals expansion, below 50 signals contraction."),
    ("gdp", "Gross Domestic Product — broadest measure of economic growth/output."),
    ("retail sales", "Tracks consumer spending at the retail level — a key demand indicator."),
    ("trade balance", "Difference between exports and imports — reflects external demand."),
    ("ism manufacturing", "Gauge of U.S. manufacturing sector activity and outlook."),
    ("ism services", "Gauge of U.S. services sector activity and outlook."),
    ("consumer confidence", "Measures household sentiment about the economy — leading indicator of spending."),
    ("consumer sentiment", "Measures household sentiment about the economy — leading indicator of spending."),
    ("building permits", "Forward-looking housing market indicator."),
    ("housing starts", "Tracks new residential construction — housing market health gauge."),
    ("durable goods", "Orders for long-lasting manufactured goods — proxy for business investment."),
    ("jobless claims", "Weekly count of new unemployment benefit filings — timely labor market signal."),
    ("ecb press conference", "ECB President's commentary following the rate decision — can move markets further."),
    ("press conference", "Central bank press conference — commentary can move markets beyond the headline decision."),
    ("employment cost index", "Tracks total cost of labor, including wages and benefits."),
    ("wage", "Tracks wage growth, an input into inflation expectations."),
]

DEFAULT_SUMMARY = "Economic data release that may influence market sentiment and volatility."


def get_event_summary(event_title: str) -> str:
    """
    Return a short plain-English explanation for an event title using the
    reusable keyword mapping table above. Falls back to a generic summary
    if no keyword matches.
    """
    title_lower = event_title.lower()
    for keyword, summary in EVENT_SUMMARY_RULES:
        if keyword in title_lower:
            return summary
    return DEFAULT_SUMMARY


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def filter_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply impact-level and currency filters from config."""
    impact_filter_upper = {level.upper() for level in config.IMPACT_FILTER}
    filtered = [
        ev
        for ev in events
        if str(ev.get("impact", "")).upper() in impact_filter_upper
        and str(ev.get("currency", "")).upper() in config.CURRENCY_FILTER
    ]
    logger.info(
        "Filtered %d/%d events (impact=%s, currencies=%s)",
        len(filtered),
        len(events),
        config.IMPACT_FILTER,
        config.CURRENCY_FILTER,
    )
    return filtered


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------
def _format_time_12h(time_str: str) -> str:
    """Convert 'HH:MM' 24h -> 'hh:MM AM/PM'. Returns 'All Day' if empty."""
    if not time_str:
        return "All Day"
    try:
        dt = datetime.strptime(time_str, "%H:%M")
        return dt.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return time_str


def build_message(events: List[Dict[str, Any]], display_date: str) -> str:
    """
    Build the final Telegram message text (Markdown-formatted) from a list
    of already-filtered events.
    """
    header = f"📅 *Forex Events — {display_date} (GMT+8)*"

    if not events:
        return (
            f"{header}\n\n"
            "No high/medium impact events scheduled for today. ✅\n\n"
            f"_Data Source: {config.DATA_SOURCE_LABEL}_"
        )

    # Group by impact level, preserving High -> Medium -> Low order.
    grouped: Dict[str, List[Dict[str, Any]]] = {level: [] for level in IMPACT_ORDER}
    for ev in events:
        grouped.setdefault(ev["impact"], []).append(ev)

    # Sort each group chronologically.
    for level in grouped:
        grouped[level].sort(key=lambda e: e.get("time", ""))

    lines = [header, ""]

    for level in IMPACT_ORDER:
        group = grouped.get(level, [])
        if not group:
            continue
        lines.append(IMPACT_HEADER.get(level, level.upper()))
        for ev in group:
            time_display = _format_time_12h(ev.get("time", ""))
            currency = ev.get("currency", "N/A")
            title = ev.get("event", "Unnamed Event")
            summary = get_event_summary(title)
            lines.append(f"{time_display} — {currency} — {title}")
            lines.append(f"Brief: {summary}")
            lines.append("")  # blank line between events
        lines.append("")  # extra spacing between impact groups

    lines.append(f"_Data Source: {config.DATA_SOURCE_LABEL}_")

    # Collapse any accidental triple-blank-lines for tidiness.
    message = "\n".join(lines)
    while "\n\n\n" in message:
        message = message.replace("\n\n\n", "\n\n")
    return message.strip()
