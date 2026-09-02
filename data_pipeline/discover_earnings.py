#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

# Ensure magic_formula package importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from magic_formula.calendar.discovery import discover_tomorrow_and_store
from magic_formula.db.repository import get_repository


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Discover T+1 earnings via MCP prioritized sources (NSE>BSE>MC) and queue into SQLite.")
    p.add_argument("--date", type=str, default=None, help="Target event date YYYY-MM-DD (default tomorrow)")
    p.add_argument("--dry-run", action="store_true", help="Do discovery without writing to DB")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    target = dt.date.today() + dt.timedelta(days=1)
    if args.date:
        target = dt.date.fromisoformat(args.date)
    if args.dry_run:
        from magic_formula.calendar.discovery import discover_for_date

        events = discover_for_date(target)
        print(f"[DryRun] {target.isoformat()}: {len(events)} symbols")
        for e in events[:50]:
            print(f"  {e.symbol} via {e.source} conf={e.confidence} url={e.source_url}")
        return
    repo = get_repository()
    count = discover_tomorrow_and_store(repo=repo, target_date=target)
    print(f"Queued {count} symbols for {target.isoformat()} (fetch at T+lag)")

    # Also show due for today with current lag
    lag = int(os.getenv("MF_FUNDAMENTAL_LAG_DAYS", "1"))
    due = repo.get_due_fundamental_symbols(as_of=dt.date.today(), lag_trading_days=lag)
    if due:
        print(f"[Due today lag={lag}] {len(due)} symbols: {', '.join(due[:30])}{'...' if len(due)>30 else ''}")


if __name__ == "__main__":
    main()
