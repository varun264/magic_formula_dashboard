from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, List, Optional, Protocol, Sequence, Tuple

from .trading_calendar import resolve_due_date

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / ".cache" / "central.db"


def _db_path_from_url(url: str) -> Path:
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///"):])
    if url.startswith("sqlite://"):
        return Path(url[len("sqlite://"):])
    return Path(url)


class FundamentalRepository(Protocol):
    def init_schema(self) -> None: ...
    def upsert_instruments(self, rows: Iterable[dict[str, Any]]) -> int: ...
    def upsert_daily_prices(self, rows: Iterable[dict[str, Any]]) -> int: ...
    def upsert_income_statement(self, rows: Iterable[dict[str, Any]]) -> int: ...
    def upsert_balance_sheet(self, rows: Iterable[dict[str, Any]]) -> int: ...
    def upsert_ratios(self, rows: Iterable[dict[str, Any]]) -> int: ...
    def upsert_earnings_calendar(self, rows: Iterable[dict[str, Any]]) -> int: ...
    def mark_calendar_fetched(self, symbol: str, event_date: str, status: str = "fetched") -> None: ...
    def get_due_fundamental_symbols(self, as_of: dt.date | None = None, lag_trading_days: int | None = None) -> List[str]: ...
    def get_latest_daily_prices(self) -> list[dict[str, Any]]: ...
    def get_v_magic_input(self) -> list[dict[str, Any]]: ...
    def log_scrape(self, symbol: str, table_name: str, source_hash: str | None = None, http_status: int | None = None, success: bool = True) -> None: ...
    def should_fetch_table(self, symbol: str, table_name: str, ttl_days: int) -> bool: ...
    def get_instrument_symbols(self) -> list[str]: ...
    def close(self) -> None: ...


class SqliteRepository:
    def __init__(self, db_path: Path | str | None = None) -> None:
        env_url = os.getenv("DATABASE_URL", "").strip()
        if db_path is None:
            if env_url:
                db_path = _db_path_from_url(env_url)
            else:
                db_path = DEFAULT_DB_PATH
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self.init_schema()

    def init_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        self._conn.executescript(sql)
        self._conn.commit()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def upsert_instruments(self, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        for r in rows:
            self._conn.execute(
                """
                INSERT INTO instruments(symbol, name, isin, sc_id, moneycontrol_slug, series, face_value, isin_number, listing_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name,
                  isin=excluded.isin,
                  sc_id=excluded.sc_id,
                  moneycontrol_slug=excluded.moneycontrol_slug,
                  series=excluded.series,
                  face_value=excluded.face_value,
                  isin_number=excluded.isin_number,
                  listing_date=excluded.listing_date,
                  updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                """,
                (
                    r.get("symbol"),
                    r.get("name"),
                    r.get("isin"),
                    r.get("sc_id"),
                    r.get("moneycontrol_slug"),
                    r.get("series"),
                    r.get("face_value"),
                    r.get("isin_number"),
                    r.get("listing_date"),
                ),
            )
            count += 1
        self._conn.commit()
        return count

    def upsert_company_profile(self, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        for r in rows:
            symbol = r.get("symbol")
            # SCD2: close previous open row if sector changed, else no-op
            cur = self._conn.execute(
                "SELECT sc_sector, sc_sector_id FROM company_profile WHERE symbol=? AND valid_to IS NULL",
                (symbol,),
            ).fetchone()
            if cur and cur["sc_sector"] == r.get("sc_sector") and cur["sc_sector_id"] == r.get("sc_sector_id"):
                continue
            if cur:
                self._conn.execute(
                    "UPDATE company_profile SET valid_to=date('now','-1 day') WHERE symbol=? AND valid_to IS NULL",
                    (symbol,),
                )
            self._conn.execute(
                """
                INSERT INTO company_profile(symbol, sc_sector_id, sc_sector, industry, link_src, pdt_dis_nm, valid_from)
                VALUES (?, ?, ?, ?, ?, ?, date('now'))
                """,
                (
                    symbol,
                    r.get("sc_sector_id"),
                    r.get("sc_sector"),
                    r.get("industry"),
                    r.get("link_src"),
                    r.get("pdt_dis_nm"),
                ),
            )
            count += 1
        self._conn.commit()
        return count

    def upsert_daily_prices(self, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        for r in rows:
            self._conn.execute(
                """
                INSERT INTO daily_prices(symbol, trade_date, close, market_cap_cr, pe_ttm, pb, dividend_yield, volume, source, source_hash, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                  close=excluded.close,
                  market_cap_cr=excluded.market_cap_cr,
                  pe_ttm=excluded.pe_ttm,
                  pb=excluded.pb,
                  dividend_yield=excluded.dividend_yield,
                  volume=excluded.volume,
                  source=excluded.source,
                  source_hash=excluded.source_hash,
                  fetched_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                """,
                (
                    r.get("symbol"),
                    r.get("trade_date"),
                    r.get("close"),
                    r.get("market_cap_cr"),
                    r.get("pe_ttm"),
                    r.get("pb"),
                    r.get("dividend_yield"),
                    r.get("volume"),
                    r.get("source", "moneycontrol"),
                    r.get("source_hash"),
                ),
            )
            count += 1
        self._conn.commit()
        return count

    def upsert_income_statement(self, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        for r in rows:
            self._conn.execute(
                """
                INSERT INTO income_statement(symbol, period_end, period, consolidation_basis, calendar_year, revenue_cr, ebit_cr, interest_cr, net_profit_cr, eps_basic, eps_diluted, cash_eps, filing_date, source_hash)
                VALUES (:symbol, :period_end, :period, :consolidation_basis, :calendar_year, :revenue_cr, :ebit_cr, :interest_cr, :net_profit_cr, :eps_basic, :eps_diluted, :cash_eps, :filing_date, :source_hash)
                ON CONFLICT(symbol, period_end, period, consolidation_basis) DO UPDATE SET
                  calendar_year=excluded.calendar_year,
                  revenue_cr=excluded.revenue_cr,
                  ebit_cr=excluded.ebit_cr,
                  interest_cr=excluded.interest_cr,
                  net_profit_cr=excluded.net_profit_cr,
                  eps_basic=excluded.eps_basic,
                  eps_diluted=excluded.eps_diluted,
                  cash_eps=excluded.cash_eps,
                  filing_date=excluded.filing_date,
                  source_hash=excluded.source_hash,
                  fetched_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                """,
                {
                    "symbol": r.get("symbol"),
                    "period_end": r.get("period_end"),
                    "period": r.get("period", "FY"),
                    "consolidation_basis": r.get("consolidation_basis", "consolidated"),
                    "calendar_year": r.get("calendar_year"),
                    "revenue_cr": r.get("revenue_cr"),
                    "ebit_cr": r.get("ebit_cr"),
                    "interest_cr": r.get("interest_cr"),
                    "net_profit_cr": r.get("net_profit_cr"),
                    "eps_basic": r.get("eps_basic"),
                    "eps_diluted": r.get("eps_diluted"),
                    "cash_eps": r.get("cash_eps"),
                    "filing_date": r.get("filing_date"),
                    "source_hash": r.get("source_hash"),
                },
            )
            count += 1
        self._conn.commit()
        return count

    def upsert_balance_sheet(self, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        for r in rows:
            self._conn.execute(
                """
                INSERT INTO balance_sheet(symbol, period_end, period, consolidation_basis, total_assets_cr, total_debt_cr, cash_and_equivalents_cr, equity_cr, book_value_per_share, shares_outstanding, source_hash)
                VALUES (:symbol, :period_end, :period, :consolidation_basis, :total_assets_cr, :total_debt_cr, :cash_and_equivalents_cr, :equity_cr, :book_value_per_share, :shares_outstanding, :source_hash)
                ON CONFLICT(symbol, period_end, period, consolidation_basis) DO UPDATE SET
                  total_assets_cr=excluded.total_assets_cr,
                  total_debt_cr=excluded.total_debt_cr,
                  cash_and_equivalents_cr=excluded.cash_and_equivalents_cr,
                  equity_cr=excluded.equity_cr,
                  book_value_per_share=excluded.book_value_per_share,
                  shares_outstanding=excluded.shares_outstanding,
                  source_hash=excluded.source_hash,
                  fetched_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                """,
                {
                    "symbol": r.get("symbol"),
                    "period_end": r.get("period_end"),
                    "period": r.get("period", "FY"),
                    "consolidation_basis": r.get("consolidation_basis", "consolidated"),
                    "total_assets_cr": r.get("total_assets_cr"),
                    "total_debt_cr": r.get("total_debt_cr"),
                    "cash_and_equivalents_cr": r.get("cash_and_equivalents_cr"),
                    "equity_cr": r.get("equity_cr"),
                    "book_value_per_share": r.get("book_value_per_share"),
                    "shares_outstanding": r.get("shares_outstanding"),
                    "source_hash": r.get("source_hash"),
                },
            )
            count += 1
        self._conn.commit()
        return count

    def upsert_ratios(self, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        for r in rows:
            self._conn.execute(
                """
                INSERT INTO ratios(symbol, period_end, period, consolidation_basis, roe_pct, roce_pct, roa_pct, debt_equity, current_ratio, quick_ratio, interest_coverage, asset_turnover, dividend_yield, payout_ratio, retention_ratio, pb, pe, source_hash)
                VALUES (:symbol, :period_end, :period, :consolidation_basis, :roe_pct, :roce_pct, :roa_pct, :debt_equity, :current_ratio, :quick_ratio, :interest_coverage, :asset_turnover, :dividend_yield, :payout_ratio, :retention_ratio, :pb, :pe, :source_hash)
                ON CONFLICT(symbol, period_end, period, consolidation_basis) DO UPDATE SET
                  roe_pct=excluded.roe_pct,
                  roce_pct=excluded.roce_pct,
                  roa_pct=excluded.roa_pct,
                  debt_equity=excluded.debt_equity,
                  current_ratio=excluded.current_ratio,
                  quick_ratio=excluded.quick_ratio,
                  interest_coverage=excluded.interest_coverage,
                  asset_turnover=excluded.asset_turnover,
                  dividend_yield=excluded.dividend_yield,
                  payout_ratio=excluded.payout_ratio,
                  retention_ratio=excluded.retention_ratio,
                  pb=excluded.pb,
                  pe=excluded.pe,
                  source_hash=excluded.source_hash,
                  fetched_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                """,
                {
                    "symbol": r.get("symbol"),
                    "period_end": r.get("period_end"),
                    "period": r.get("period", "FY"),
                    "consolidation_basis": r.get("consolidation_basis", "consolidated"),
                    "roe_pct": r.get("roe_pct"),
                    "roce_pct": r.get("roce_pct"),
                    "roa_pct": r.get("roa_pct"),
                    "debt_equity": r.get("debt_equity"),
                    "current_ratio": r.get("current_ratio"),
                    "quick_ratio": r.get("quick_ratio"),
                    "interest_coverage": r.get("interest_coverage"),
                    "asset_turnover": r.get("asset_turnover"),
                    "dividend_yield": r.get("dividend_yield"),
                    "payout_ratio": r.get("payout_ratio"),
                    "retention_ratio": r.get("retention_ratio"),
                    "pb": r.get("pb"),
                    "pe": r.get("pe"),
                    "source_hash": r.get("source_hash"),
                },
            )
            count += 1
        self._conn.commit()
        return count

    def upsert_earnings_calendar(self, rows: Iterable[dict[str, Any]]) -> int:
        count = 0
        for r in rows:
            self._conn.execute(
                """
                INSERT INTO earnings_calendar(symbol, event_date, source, source_url, result_type, confidence, status)
                VALUES (:symbol, :event_date, :source, :source_url, :result_type, :confidence, :status)
                ON CONFLICT(symbol, event_date, source) DO UPDATE SET
                  source_url=excluded.source_url,
                  result_type=excluded.result_type,
                  confidence=excluded.confidence,
                  status=excluded.status
                """,
                {
                    "symbol": r.get("symbol"),
                    "event_date": r.get("event_date"),
                    "source": r.get("source", "NSE"),
                    "source_url": r.get("source_url"),
                    "result_type": r.get("result_type", "quarterly"),
                    "confidence": r.get("confidence", 1.0),
                    "status": r.get("status", "pending"),
                },
            )
            count += 1
        self._conn.commit()
        return count

    def mark_calendar_fetched(self, symbol: str, event_date: str, status: str = "fetched") -> None:
        self._conn.execute(
            "UPDATE earnings_calendar SET status=? WHERE symbol=? AND event_date=?",
            (status, symbol, event_date),
        )
        self._conn.commit()

    def get_due_fundamental_symbols(self, as_of: dt.date | None = None, lag_trading_days: int | None = None) -> List[str]:
        if as_of is None:
            as_of = dt.date.today()
        if lag_trading_days is None:
            lag_trading_days = int(os.getenv("MF_FUNDAMENTAL_LAG_DAYS", "1"))
        # Find events where due_date == as_of and still pending
        rows = self._conn.execute(
            "SELECT symbol, event_date, source, confidence FROM earnings_calendar WHERE status='pending'"
        ).fetchall()
        due: list[str] = []
        for r in rows:
            due_date = resolve_due_date(r["event_date"], lag_trading_days)
            if due_date <= as_of:
                due.append(r["symbol"])
        # Also include manually flagged stale fundamentals: no income_statement in 90 days for FY, 35 days for Q
        # Handled separately by caller as fallback; here return only calendar due
        return sorted(set(due))

    def get_stale_fundamental_symbols(self, ttl_days_fy: int = 90, ttl_days_q: int = 35) -> List[str]:
        # Symbols with no fundamentals yet or fundamentals older than TTL
        all_syms = self.get_instrument_symbols()
        stale: list[str] = []
        for sym in all_syms:
            row = self._conn.execute(
                "SELECT MAX(period_end) as last_fy FROM income_statement WHERE symbol=? AND period='FY'",
                (sym,),
            ).fetchone()
            if row["last_fy"] is None:
                stale.append(sym)
                continue
            last = dt.date.fromisoformat(row["last_fy"]) if "T" not in row["last_fy"] else dt.date.fromisoformat(row["last_fy"][:10])
            if (dt.date.today() - last).days > ttl_days_fy:
                stale.append(sym)
        return stale

    def get_latest_daily_prices(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            """
            SELECT dp.* FROM daily_prices dp
            JOIN (SELECT symbol, MAX(trade_date) as md FROM daily_prices GROUP BY symbol) m
              ON m.symbol=dp.symbol AND m.md=dp.trade_date
            """
        )
        return [dict(r) for r in cur.fetchall()]

    def get_v_magic_input(self) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM v_magic_input")
        return [dict(r) for r in cur.fetchall()]

    def log_scrape(self, symbol: str, table_name: str, source_hash: str | None = None, http_status: int | None = None, success: bool = True) -> None:
        self._conn.execute(
            "INSERT INTO scrape_log(symbol, table_name, http_status, source_hash, success) VALUES (?, ?, ?, ?, ?)",
            (symbol, table_name, http_status, source_hash, 1 if success else 0),
        )
        self._conn.commit()

    def should_fetch_table(self, symbol: str, table_name: str, ttl_days: int) -> bool:
        row = self._conn.execute(
            "SELECT MAX(fetched_at) as last FROM scrape_log WHERE symbol=? AND table_name=? AND success=1",
            (symbol, table_name),
        ).fetchone()
        if row["last"] is None:
            return True
        try:
            last = dt.datetime.fromisoformat(row["last"].replace("Z", "+00:00"))
            age = (dt.datetime.now(dt.timezone.utc) - last).days
            return age >= ttl_days
        except Exception:
            return True

    def get_instrument_symbols(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT symbol FROM instruments ORDER BY symbol").fetchall()]

    def get_earnings_calendar(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            cur = self._conn.execute("SELECT * FROM earnings_calendar WHERE status=? ORDER BY event_date", (status,))
        else:
            cur = self._conn.execute("SELECT * FROM earnings_calendar ORDER BY event_date")
        return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        try:
            self._conn.commit()
            self._conn.close()
        except Exception:
            pass


def get_repository(db_path: Path | str | None = None) -> SqliteRepository:
    url = os.getenv("DATABASE_URL", "").strip()
    if url and not url.startswith("sqlite"):
        raise ValueError(f"Unsupported DATABASE_URL for now: {url}. Only sqlite:// supported; extend via factory for Postgres.")
    if db_path is None and url:
        return SqliteRepository(_db_path_from_url(url))
    return SqliteRepository(db_path)


def hash_record(record: dict[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, default=str)
    return hashlib.md5(payload.encode()).hexdigest()
