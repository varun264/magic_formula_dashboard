from __future__ import annotations

import datetime as dt
from typing import List, Sequence

import pandas as pd

from ..db.repository import SqliteRepository
from ..services.mappers import to_balance_sheet, to_company_profile, to_daily_price, to_income_statement, to_ratios
from ..services.stock_fetcher import StockDataFetcher
from ..utils.chunk import chunked


def sync_instruments(repo: SqliteRepository, symbols_df: pd.DataFrame) -> int:
    from ..services.mappers import to_instruments

    rows = to_instruments(symbols_df)
    return repo.upsert_instruments(rows)


def run_price_daily(
    repo: SqliteRepository,
    fetcher: StockDataFetcher,
    symbols: Sequence[str],
    batch_size: int = 100,
    max_workers: int = 6,
    trade_date: str | None = None,
) -> tuple[int, int]:
    if trade_date is None:
        trade_date = dt.date.today().isoformat()
    total = 0
    failures = 0
    for chunk in chunked(list(symbols), batch_size):
        batch = fetcher.fetch_price_many(chunk, max_workers=max_workers)
        if batch.empty:
            failures += len(chunk)
            continue
        rows: List[dict] = []
        profile_rows: List[dict] = []
        for _, rec in batch.iterrows():
            rec_dict = rec.to_dict()
            symbol = rec_dict.get("_nse_symbol") or rec_dict.get("_sc_id") or rec_dict.get("symbol") or rec_dict.get("sc_id")
            if not symbol:
                continue
            # _nse_symbol is canonical NSE symbol from input list
            if "_nse_symbol" in rec_dict and rec_dict["_nse_symbol"]:
                symbol = rec_dict["_nse_symbol"]
            else:
                try:
                    row = repo._conn.execute("SELECT symbol FROM instruments WHERE sc_id=?", (symbol,)).fetchone()
                    if row:
                        symbol = row[0]
                except Exception:
                    pass
            if not symbol:
                continue
            rows.append(to_daily_price(symbol, rec_dict, trade_date))
            profile_rows.append(to_company_profile(symbol, rec_dict))
        if rows:
            repo.upsert_daily_prices(rows)
            try:
                repo.upsert_company_profile(profile_rows)
            except Exception:
                pass
            total += len(rows)
    return total, failures


def run_fundamentals_for_symbols(
    repo: SqliteRepository,
    fetcher: StockDataFetcher,
    symbols: Sequence[str],
    batch_size: int = 100,
    max_workers: int = 6,
    period_end: str | None = None,
) -> tuple[int, int]:
    if not symbols:
        return 0, 0
    if period_end is None:
        period_end = dt.date.today().isoformat()
    total = 0
    failures = 0
    for chunk in chunked(list(symbols), batch_size):
        batch = fetcher.fetch_many(chunk, max_workers=max_workers)
        if batch.empty:
            failures += len(chunk)
            continue
        inc_rows: List[dict] = []
        bs_rows: List[dict] = []
        ratio_rows: List[dict] = []
        for _, rec in batch.iterrows():
            rec_dict = rec.to_dict()
            symbol = rec_dict.get("_nse_symbol") or rec_dict.get("_sc_id") or rec_dict.get("symbol") or rec_dict.get("sc_id")
            if not symbol:
                continue
            if "_nse_symbol" in rec_dict and rec_dict["_nse_symbol"]:
                symbol = rec_dict["_nse_symbol"]
            else:
                try:
                    row = repo._conn.execute("SELECT symbol FROM instruments WHERE sc_id=?", (symbol,)).fetchone()
                    if row:
                        symbol = row[0]
                except Exception:
                    pass
                if not symbol or len(symbol) > 12:
                    name = rec_dict.get("name") or rec_dict.get("stock_name")
                    if name:
                        try:
                            r2 = repo._conn.execute("SELECT symbol FROM instruments WHERE name LIKE ?", (f"%{name}%",)).fetchone()
                            if r2:
                                symbol = r2[0]
                        except Exception:
                            pass
            if not symbol:
                continue
            inc_rows.append(to_income_statement(symbol, rec_dict, period_end))
            bs_rows.append(to_balance_sheet(symbol, rec_dict, period_end))
            ratio_rows.append(to_ratios(symbol, rec_dict, period_end))
        if inc_rows:
            repo.upsert_income_statement(inc_rows)
            repo.upsert_balance_sheet(bs_rows)
            repo.upsert_ratios(ratio_rows)
            total += len(inc_rows)
            # mark calendar fetched
            for sym in [r["symbol"] for r in inc_rows]:
                # find pending events for this symbol due today/earlier
                try:
                    pending = repo._conn.execute(
                        "SELECT event_date FROM earnings_calendar WHERE symbol=? AND status='pending'", (sym,)
                    ).fetchall()
                    for prow in pending:
                        repo.mark_calendar_fetched(sym, prow[0], "fetched")
                except Exception:
                    pass
    return total, failures
