"""Weeks.

The token is a counter of market-days. The storefront sells weeks, because a
week is something a buyer can reason about and a bare number is not: "84" means
nothing until you are told it is twelve weeks of one market, or four across
three.

Nothing here constrains anything. A buyer can spend their allowance on
scattered single days if they want to. These helpers exist so the tools speak
the same language the product page does, and so the week-shaped path is the
convenient one.

Weeks are Monday to Sunday in Asia/Tokyo, matching how the data is partitioned.
"""

from datetime import date, timedelta

DAYS_PER_WEEK = 7


def week_start(d: str | date) -> date:
    """The Monday of the week containing this date."""
    day = date.fromisoformat(d) if isinstance(d, str) else d
    return day - timedelta(days=day.weekday())


def week_label(d: str | date) -> str:
    """ISO week, as `2025-W27`."""
    day = date.fromisoformat(d) if isinstance(d, str) else d
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def week_range(start: str, weeks: int) -> tuple[str, str]:
    """The date range covering `weeks` whole weeks from `start`.

    The start is not snapped to a Monday. A buyer asking for four weeks from a
    Wednesday means twenty-eight days from that Wednesday, and silently moving
    their start would spend their allowance somewhere they did not ask for.
    """
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    first = date.fromisoformat(start)
    last = first + timedelta(days=weeks * DAYS_PER_WEEK - 1)
    return first.isoformat(), last.isoformat()


def describe(market_days: int) -> str:
    """Render an allowance the way the storefront describes it."""
    if market_days == 0:
        return "none"
    weeks, spare = divmod(market_days, DAYS_PER_WEEK)
    if not weeks:
        return f"{market_days} market-day{'s' if market_days > 1 else ''}"
    text = f"{weeks} market-week{'s' if weeks > 1 else ''}"
    if spare:
        text += f" and {spare} day{'s' if spare > 1 else ''}"
    return text


def shapes(market_days: int, markets: int = 4) -> list[str]:
    """Week-shaped ways to spend an allowance, for showing a buyer their options."""
    weeks = market_days // DAYS_PER_WEEK
    out = []
    for n in range(1, markets + 1):
        if weeks and weeks % n == 0:
            w = weeks // n
            out.append(f"{w} week{'s' if w > 1 else ''} x {n} market{'s' if n > 1 else ''}")
    return out
