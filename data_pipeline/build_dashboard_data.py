from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from magic_formula import (
    CSVWriter,
    MagicFormulaDatasetPipeline,
    MoneyControlClient,
    OverviewParser,
    ProfitLossParser,
    QuarterlyResultsParser,
    RatiosParser,
    StockDataFetcher,
)

try:
    from magic_formula.calendar.discovery import discover_tomorrow_and_store
    from magic_formula.db.repository import get_repository
    from magic_formula.db.trading_calendar import is_trading_day
    from magic_formula.pipelines.db_pipeline import run_fundamentals_for_symbols, run_price_daily, sync_instruments
    from magic_formula.services.mappers import to_instruments

    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False


ROOT_DIR = Path(__file__).resolve().parents[1]
PIPELINE_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "public" / "data"
CACHE_DIR = ROOT_DIR / ".cache" / "magic_formula"
SYMBOLS_FILE = PIPELINE_DIR / "nse_stocks.csv"
SEED_DATA_FILE = PIPELINE_DIR / "stock_data_master_seed.csv"
RAW_DATA_FILE = CACHE_DIR / "stock_data_master.csv"
LATEST_JSON_FILE = DATA_DIR / "latest.json"
LATEST_CSV_FILE = DATA_DIR / "magic_formula_top50.csv"

MIN_MARKET_CAP_RS = float(os.getenv("MF_MIN_MARKET_CAP_RS", 5_000 * 1e7))
TOP_N = int(os.getenv("MF_TOP_N", "50"))
VALUATION_TAX_RATE = float(os.getenv("MF_VALUATION_TAX_RATE", "0.25"))
VALUATION_REQUIRED_EARNINGS_YIELD = float(os.getenv("MF_VALUATION_REQUIRED_EARNINGS_YIELD", "0.10"))
if VALUATION_REQUIRED_EARNINGS_YIELD <= 0:
    raise ValueError("MF_VALUATION_REQUIRED_EARNINGS_YIELD must be greater than zero.")
DEFAULT_BATCH_SIZE = int(os.getenv("MF_BATCH_SIZE", "100"))
DEFAULT_MAX_WORKERS = int(os.getenv("MF_MAX_WORKERS", "6"))
DEFAULT_TIMEOUT = float(os.getenv("MF_TIMEOUT", "12"))
DEFAULT_RETRIES = int(os.getenv("MF_RETRIES", "3"))
DEFAULT_BACKOFF = float(os.getenv("MF_BACKOFF", "1"))

REQUIRED_COLUMNS = [
    "name",
    "Mkt Cap (Rs. Cr.)",
    "Previous Close",
    "PBIT/Share (Rs.)",
    "Enterprise Value (Cr.)",
    "Return on Capital Employed (%)",
]


def _to_numeric(series: pd.Series, *, multiply: float = 1.0) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce") * multiply


def load_symbols(path: Path, *, offset: int = 0, limit: int | None = None) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Symbols file not found: {path}")

    symbols = pd.read_csv(path)["SYMBOL"].dropna().astype(str).tolist()
    if offset:
        symbols = symbols[offset:]
    if limit is not None:
        symbols = symbols[:limit]
    return symbols


def build_fetcher() -> StockDataFetcher:
    def client_factory() -> MoneyControlClient:
        return MoneyControlClient(
            verify_ssl=False,
            timeout=DEFAULT_TIMEOUT,
            max_retries=DEFAULT_RETRIES,
            backoff_factor=DEFAULT_BACKOFF,
        )

    return StockDataFetcher(
        client_factory=client_factory,
        overview_parser=OverviewParser(),
        profit_loss_parser=ProfitLossParser(),
        quarterly_parser=QuarterlyResultsParser(),
        ratios_parser=RatiosParser(),
    )


def scrape_master_data(symbols: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    writer = CSVWriter(RAW_DATA_FILE, overwrite=True)
    failures: list[tuple[str, str]] = []

    def on_error(symbol: str, error: Exception) -> None:
        failures.append((symbol, str(error)))
        print(f"[Error] Failed to process {symbol}: {error}")

    fetcher = build_fetcher()
    fetcher._error_handler = on_error
    pipeline = MagicFormulaDatasetPipeline(fetcher, writer)
    pipeline.run(symbols, batch_size=DEFAULT_BATCH_SIZE, max_workers=DEFAULT_MAX_WORKERS)

    if not RAW_DATA_FILE.exists():
        raise RuntimeError("Scraper completed without producing a master CSV.")

    scraped_rows = len(pd.read_csv(RAW_DATA_FILE, usecols=["name"]))
    expected = len(symbols)
    success_rate = scraped_rows / expected if expected else 0.0

    print(
        f"[Summary] Scraped {scraped_rows}/{expected} symbols "
        f"({success_rate:.0%}); {len(failures)} failures."
    )

    min_success_rate = float(os.getenv("MF_MIN_SUCCESS_RATE", "0.6"))
    if success_rate < min_success_rate:
        sample = ", ".join(symbol for symbol, _ in failures[:20])
        raise RuntimeError(
            f"Scrape success rate {success_rate:.0%} is below the required "
            f"{min_success_rate:.0%}. First failures: {sample}"
        )


def ensure_db_initialized() -> None:
    if not _DB_AVAILABLE:
        return
    repo = get_repository()
    repo.init_schema()
    if not repo.get_instrument_symbols():
        try:
            df = pd.read_csv(SYMBOLS_FILE, dtype=str).fillna("")
            rows = to_instruments(df)
            n = sync_instruments(repo, df)
            print(f"[DB] Initialized {n} instruments")
        except Exception as e:
            print(f"[DB] instrument init warn: {e}")


def scrape_master_data(symbols: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    writer = CSVWriter(RAW_DATA_FILE, overwrite=True)
    failures: list[tuple[str, str]] = []

    def on_error(symbol: str, error: Exception) -> None:
        failures.append((symbol, str(error)))
        print(f"[Error] Failed to process {symbol}: {error}")

    fetcher = build_fetcher()
    fetcher._error_handler = on_error
    pipeline = MagicFormulaDatasetPipeline(fetcher, writer)
    pipeline.run(symbols, batch_size=DEFAULT_BATCH_SIZE, max_workers=DEFAULT_MAX_WORKERS)

    if not RAW_DATA_FILE.exists():
        raise RuntimeError("Scraper completed without producing a master CSV.")

    scraped_rows = len(pd.read_csv(RAW_DATA_FILE, usecols=["name"]))
    expected = len(symbols)
    success_rate = scraped_rows / expected if expected else 0.0

    print(
        f"[Summary] Scraped {scraped_rows}/{expected} symbols "
        f"({success_rate:.0%}); {len(failures)} failures."
    )

    min_success_rate = float(os.getenv("MF_MIN_SUCCESS_RATE", "0.6"))
    if success_rate < min_success_rate:
        sample = ", ".join(symbol for symbol, _ in failures[:20])
        raise RuntimeError(
            f"Scrape success rate {success_rate:.0%} is below the required "
            f"{min_success_rate:.0%}. First failures: {sample}"
        )


def run_price_daily_db(symbols: list[str] | None = None) -> None:
    if not _DB_AVAILABLE:
        raise RuntimeError("DB layer unavailable")
    ensure_db_initialized()
    repo = get_repository()
    if symbols is None:
        symbols = load_symbols(SYMBOLS_FILE)
    fetcher = build_fetcher()
    total, fails = run_price_daily(repo, fetcher, symbols, batch_size=DEFAULT_BATCH_SIZE, max_workers=DEFAULT_MAX_WORKERS)
    print(f"[PriceDaily] upserted {total} daily_prices, failures {fails}")


def run_fundamentals_due_db(symbols: list[str] | None = None, lag: int | None = None) -> None:
    if not _DB_AVAILABLE:
        raise RuntimeError("DB layer unavailable")
    ensure_db_initialized()
    repo = get_repository()
    import datetime as _dt

    if lag is None:
        lag = int(os.getenv("MF_FUNDAMENTAL_LAG_DAYS", "1"))
    if symbols is not None:
        due = symbols
    else:
        due = repo.get_due_fundamental_symbols(as_of=_dt.date.today(), lag_trading_days=lag)
        if not due:
            stale = repo.get_stale_fundamental_symbols()
            if stale:
                # cap stale backfill to 100 per run to avoid thundering herd
                due = stale[: int(os.getenv("MF_STALE_BACKFILL_LIMIT", "20"))]
                if due:
                    print(f"[Fundamentals] no calendar due; backfilling {len(due)} stale symbols")
    if not due:
        print("[Fundamentals] no due symbols for today (calendar empty, no stale)")
        return
    print(f"[Fundamentals] due {len(due)} symbols (lag={lag}): {', '.join(due[:20])}{'...' if len(due)>20 else ''}")
    fetcher = build_fetcher()
    total, fails = run_fundamentals_for_symbols(repo, fetcher, due, batch_size=max(10, DEFAULT_BATCH_SIZE // 2), max_workers=DEFAULT_MAX_WORKERS)
    print(f"[Fundamentals] upserted {total} fundamentals, failures {fails}")


def build_from_db() -> Path:
    if not _DB_AVAILABLE:
        raise RuntimeError("DB layer unavailable")
    ensure_db_initialized()
    repo = get_repository()
    rows = repo.get_v_magic_input()
    if not rows:
        raise RuntimeError("v_magic_input empty — run --seed-db or --price-only/--fundamentals first")
    df = pd.DataFrame(rows)
    # Map view cols to REQUIRED_COLUMNS shape
    # v_magic_input has: symbol, name, sc_sector, ebit_cr, book_value_per_share, roce_pct, previous_close, market_cap_cr, trade_date
    # We need to synthesize columns required by compute logic
    df = df.rename(columns={"name": "name", "market_cap_cr": "Mkt Cap (Rs. Cr.)", "previous_close": "Previous Close"})
    # Derive required derived columns via same logic as models.py but DB already has components
    # Ensure PBIT/Share and Enterprise Value and ROC exist
    df["Enterprise Value (Cr.)"] = df["Mkt Cap (Rs. Cr.)"]
    # PBIT/Share = EBIT * close / mcap
    import numpy as _np

    ebit = pd.to_numeric(df["ebit_cr"], errors="coerce")
    mcap = pd.to_numeric(df["Mkt Cap (Rs. Cr.)"], errors="coerce")
    close = pd.to_numeric(df["Previous Close"], errors="coerce")
    bvps = pd.to_numeric(df["book_value_per_share"], errors="coerce")
    df["PBIT/Share (Rs.)"] = (ebit * close) / mcap
    equity = (bvps * mcap) / close
    df["Return on Capital Employed (%)"] = (ebit / equity) * 100
    # Need sc_sector column
    if "sc_sector" not in df.columns:
        df["sc_sector"] = None
    # Fill other raw columns expected downstream (for details, provide minimal)
    # Persist merged frame to RAW_DATA_FILE for reuse by compute_magic_formula
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Enrich with full fundamentals details from DB for richest details blob
    # Pull ratios/balance extra for details via joins (best-effort)
    try:
        repo = get_repository()
        for idx, row in df.iterrows():
            sym = row["symbol"] if "symbol" in row else None
            if not sym:
                continue
            extra = repo._conn.execute(
                "SELECT * FROM ratios WHERE symbol=? ORDER BY period_end DESC LIMIT 1", (sym,)
            ).fetchone()
            if extra:
                for k in extra.keys():
                    if k not in df.columns and k not in ("symbol", "period_end"):
                        df.at[idx, k] = extra[k]
    except Exception:
        pass
    df.to_csv(RAW_DATA_FILE, index=False)
    print(f"[DB] wrote magic_input -> {RAW_DATA_FILE} ({len(df)} rows)")
    return RAW_DATA_FILE


def ensure_master_data(scrape: bool, *, offset: int, limit: int | None) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if scrape:
        symbols = load_symbols(SYMBOLS_FILE, offset=offset, limit=limit)
        scrape_master_data(symbols)
        return RAW_DATA_FILE

    if not RAW_DATA_FILE.exists():
        if not SEED_DATA_FILE.exists():
            raise FileNotFoundError(f"No generated or seed data found at {RAW_DATA_FILE} or {SEED_DATA_FILE}")
        shutil.copyfile(SEED_DATA_FILE, RAW_DATA_FILE)

    return RAW_DATA_FILE


def compute_magic_formula(input_path: Path) -> tuple[pd.DataFrame, int]:
    df = pd.read_csv(input_path)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    market_cap_rs = _to_numeric(df["Mkt Cap (Rs. Cr.)"], multiply=1e7)
    previous_close = _to_numeric(df["Previous Close"])
    pbit_share = _to_numeric(df["PBIT/Share (Rs.)"])
    enterprise_value_rs = _to_numeric(df["Enterprise Value (Cr.)"], multiply=1e7)
    roc = _to_numeric(df["Return on Capital Employed (%)"], multiply=0.01)
    shares = market_cap_rs / previous_close
    ebit = pbit_share * shares

    ranked = df.assign(
        market_cap_cr=market_cap_rs / 1e7,
        previous_close=previous_close,
        pbit_per_share=pbit_share,
        owner_earnings_per_share=pbit_share * (1 - VALUATION_TAX_RATE),
        intrinsic_value=(pbit_share * (1 - VALUATION_TAX_RATE)) / VALUATION_REQUIRED_EARNINGS_YIELD,
        enterprise_value_cr=enterprise_value_rs / 1e7,
        ebit_rs=ebit,
        earnings_yield=ebit / enterprise_value_rs,
        return_on_capital=roc,
    )
    ranked["margin_of_safety"] = (ranked["intrinsic_value"] / ranked["previous_close"]) - 1

    ranked = ranked.replace([np.inf, -np.inf], np.nan)
    ranked = ranked.dropna(
        subset=[
            "name",
            "earnings_yield",
            "return_on_capital",
            "market_cap_cr",
            "enterprise_value_cr",
            "previous_close",
            "intrinsic_value",
            "margin_of_safety",
        ]
    )
    ranked = ranked[(ranked["enterprise_value_cr"] > 0) & (ranked["market_cap_cr"] * 1e7 > MIN_MARKET_CAP_RS)]

    if ranked.empty:
        raise ValueError("No rows remaining after applying Magic Formula filters.")

    ranked = ranked.copy()
    ranked["ey_rank"] = ranked["earnings_yield"].rank(ascending=False, method="min")
    ranked["roc_rank"] = ranked["return_on_capital"].rank(ascending=False, method="min")
    ranked["combined_rank"] = ranked["ey_rank"] + ranked["roc_rank"]
    ranked = ranked.sort_values(["combined_rank", "ey_rank", "roc_rank"]).drop_duplicates(subset=["name"], keep="first")
    ranked["magic_formula_rank"] = range(1, len(ranked) + 1)

    output_columns = [
        "magic_formula_rank",
        "name",
        "sc_sector",
        "market_cap_cr",
        "previous_close",
        "pbit_per_share",
        "owner_earnings_per_share",
        "intrinsic_value",
        "margin_of_safety",
        "enterprise_value_cr",
        "earnings_yield",
        "return_on_capital",
        "ey_rank",
        "roc_rank",
        "combined_rank",
    ]
    existing_output_columns = [column for column in output_columns if column in ranked.columns]
    top_ranked = ranked.head(TOP_N).copy()
    recommendations = top_ranked.loc[:, existing_output_columns].copy()
    recommendations["details"] = top_ranked.apply(
        lambda row: {
            str(column): clean_for_json(row[column])
            for column in top_ranked.columns
            if column != "details" and not pd.isna(row[column])
        },
        axis=1,
    )
    return recommendations, len(ranked)


def clean_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_for_json(nested_value) for key, nested_value in value.items()}
    if isinstance(value, list):
        return [clean_for_json(item) for item in value]
    if pd.isna(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def write_dashboard_files(recommendations: pd.DataFrame, *, ranked_count: int, raw_count: int, scraped: bool) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    recommendations.drop(columns=["details"], errors="ignore").to_csv(LATEST_CSV_FILE, index=False)

    records = [
        {key: clean_for_json(value) for key, value in record.items()}
        for record in recommendations.to_dict(orient="records")
    ]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Moneycontrol",
        "scraped": scraped,
        "filters": {
            "minimum_market_cap_rs": MIN_MARKET_CAP_RS,
            "top_n": TOP_N,
        },
        "valuation": {
            "method": "Earnings power value",
            "formula": "intrinsic_value = PBIT/share * (1 - tax_rate) / required_earnings_yield",
            "tax_rate": VALUATION_TAX_RATE,
            "required_earnings_yield": VALUATION_REQUIRED_EARNINGS_YIELD,
            "pbit_share_method": "Annual EBIT (profit-loss page) * previous_close / market_cap",
            "enterprise_value_method": "market cap proxy (net debt not subtracted)",
            "return_on_capital_method": "Annual EBIT / book equity, where book equity = BVPS * market_cap / previous_close",
        },
        "counts": {
            "raw_rows": raw_count,
            "ranked_rows": ranked_count,
            "recommendation_rows": len(records),
        },
        "recommendations": records,
    }

    LATEST_JSON_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build static Magic Formula dashboard data.")
    parser.add_argument("--scrape", action="store_true", help="Refresh Moneycontrol data before ranking.")
    parser.add_argument("--price-only", action="store_true", help="Fetch only price/daily (overview+ratios) into DB and rebuild from DB.")
    parser.add_argument("--fundamentals", action="store_true", help="Fetch fundamentals for due symbols (calendar + lag) into DB and rebuild.")
    parser.add_argument("--from-db", action="store_true", help="Build latest.json from DB view without scraping.")
    parser.add_argument("--seed-db", action="store_true", help="Seed SQLite DB from nse_stocks.csv + stock_data_master_seed.csv.")
    parser.add_argument("--discover", action="store_true", help="Run MCP discovery for T+1 and queue into earnings_calendar.")
    parser.add_argument("--discover-date", type=str, default=None, help="Target date for --discover (YYYY-MM-DD), default tomorrow")
    parser.add_argument("--symbol-offset", type=int, default=int(os.getenv("MF_SYMBOL_OFFSET", "0")))
    parser.add_argument("--symbol-limit", type=int, default=None)
    args = parser.parse_args()

    env_symbol_limit = os.getenv("MF_SYMBOL_LIMIT")
    symbol_limit = args.symbol_limit if args.symbol_limit is not None else int(env_symbol_limit) if env_symbol_limit else None

    if args.seed_db:
        if not _DB_AVAILABLE:
            raise RuntimeError("--seed-db requires DB layer")
        import subprocess

        subprocess.run([sys.executable, str(PIPELINE_DIR / "seed_db.py")], check=True)
        if args.from_db or args.price_only or args.fundamentals:
            pass
        else:
            # also show due
            master_path = build_from_db()
            recommendations, ranked_count = compute_magic_formula(master_path)
            raw_count = len(pd.read_csv(master_path, usecols=["name"]))
            write_dashboard_files(recommendations, ranked_count=ranked_count, raw_count=raw_count, scraped=False)
            print(f"Wrote {len(recommendations)} recommendations to {LATEST_JSON_FILE} (from DB)")
            return

    if args.discover:
        if not _DB_AVAILABLE:
            raise RuntimeError("--discover requires DB layer")
        import datetime as _dt

        target = (_dt.date.fromisoformat(args.discover_date) if args.discover_date else _dt.date.today() + _dt.timedelta(days=1))
        discover_tomorrow_and_store(target_date=target)
        return

    if args.price_only:
        symbols = load_symbols(SYMBOLS_FILE, offset=args.symbol_offset, limit=symbol_limit)
        run_price_daily_db(symbols)
        master_path = build_from_db()
        recommendations, ranked_count = compute_magic_formula(master_path)
        raw_count = len(pd.read_csv(master_path, usecols=["name"]))
        write_dashboard_files(recommendations, ranked_count=ranked_count, raw_count=raw_count, scraped=True)
        print(f"Wrote {len(recommendations)} recommendations to {LATEST_JSON_FILE} (price-only -> DB)")
        return

    if args.fundamentals:
        run_fundamentals_due_db()
        master_path = build_from_db()
        recommendations, ranked_count = compute_magic_formula(master_path)
        raw_count = len(pd.read_csv(master_path, usecols=["name"]))
        write_dashboard_files(recommendations, ranked_count=ranked_count, raw_count=raw_count, scraped=True)
        print(f"Wrote {len(recommendations)} recommendations to {LATEST_JSON_FILE} (fundamentals due -> DB)")
        return

    if args.from_db:
        master_path = build_from_db()
        recommendations, ranked_count = compute_magic_formula(master_path)
        raw_count = len(pd.read_csv(master_path, usecols=["name"]))
        write_dashboard_files(recommendations, ranked_count=ranked_count, raw_count=raw_count, scraped=False)
        print(f"Wrote {len(recommendations)} recommendations to {LATEST_JSON_FILE} (from DB)")
        return

    # legacy path
    master_path = ensure_master_data(args.scrape, offset=args.symbol_offset, limit=symbol_limit)
    recommendations, ranked_count = compute_magic_formula(master_path)
    raw_count = len(pd.read_csv(master_path, usecols=["name"]))
    write_dashboard_files(recommendations, ranked_count=ranked_count, raw_count=raw_count, scraped=args.scrape)
    print(f"Wrote {len(recommendations)} recommendations to {LATEST_JSON_FILE}")


if __name__ == "__main__":
    main()
