from __future__ import annotations

import argparse
import json
import os
import shutil
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
    RatiosParser,
    StockDataFetcher,
)


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
DEFAULT_MAX_WORKERS = int(os.getenv("MF_MAX_WORKERS", "8"))
DEFAULT_TIMEOUT = float(os.getenv("MF_TIMEOUT", "20"))
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
        ratios_parser=RatiosParser(),
    )


def scrape_master_data(symbols: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    writer = CSVWriter(RAW_DATA_FILE, overwrite=True)
    pipeline = MagicFormulaDatasetPipeline(build_fetcher(), writer)
    pipeline.run(symbols, batch_size=DEFAULT_BATCH_SIZE, max_workers=DEFAULT_MAX_WORKERS)

    if not RAW_DATA_FILE.exists():
        raise RuntimeError("Scraper completed without producing a master CSV.")


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
    return ranked.loc[:, existing_output_columns].head(TOP_N), len(ranked)


def clean_for_json(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def write_dashboard_files(recommendations: pd.DataFrame, *, ranked_count: int, raw_count: int, scraped: bool) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    recommendations.to_csv(LATEST_CSV_FILE, index=False)

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
    parser.add_argument("--symbol-offset", type=int, default=int(os.getenv("MF_SYMBOL_OFFSET", "0")))
    parser.add_argument("--symbol-limit", type=int, default=None)
    args = parser.parse_args()

    env_symbol_limit = os.getenv("MF_SYMBOL_LIMIT")
    symbol_limit = args.symbol_limit if args.symbol_limit is not None else int(env_symbol_limit) if env_symbol_limit else None
    master_path = ensure_master_data(args.scrape, offset=args.symbol_offset, limit=symbol_limit)
    recommendations, ranked_count = compute_magic_formula(master_path)
    raw_count = len(pd.read_csv(master_path, usecols=["name"]))
    write_dashboard_files(recommendations, ranked_count=ranked_count, raw_count=raw_count, scraped=args.scrape)
    print(f"Wrote {len(recommendations)} recommendations to {LATEST_JSON_FILE}")


if __name__ == "__main__":
    main()
