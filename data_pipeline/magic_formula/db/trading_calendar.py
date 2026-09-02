from __future__ import annotations

import datetime as dt
import os


NSE_HOLIDAYS: set[str] = set(
    # Minimal static list; extend via env MF_EXTRA_HOLIDAYS=2026-01-26,2026-08-15
    # Full NSE calendar can be loaded from file or API later.
    filter(
        None,
        os.getenv("MF_EXTRA_HOLIDAYS", "").replace(" ", "").split(","),
    )
)


def is_trading_day(date: dt.date) -> bool:
    if date.weekday() >= 5:
        return False
    if date.isoformat() in NSE_HOLIDAYS:
        return False
    return True


def next_trading_day(date: dt.date, offset: int = 1) -> dt.date:
    cur = date
    steps = 0
    while steps < offset:
        cur += dt.timedelta(days=1)
        if is_trading_day(cur):
            steps += 1
    return cur


def add_trading_days(date: dt.date, trading_days: int) -> dt.date:
    if trading_days <= 0:
        return date
    return next_trading_day(date, trading_days)


def trading_lag_date(event_date: dt.date, lag_trading_days: int) -> dt.date:
    return add_trading_days(event_date, lag_trading_days)


def resolve_due_date(event_date: dt.date | str, lag: int) -> dt.date:
    if isinstance(event_date, str):
        event_date = dt.date.fromisoformat(event_date)
    return trading_lag_date(event_date, lag)
