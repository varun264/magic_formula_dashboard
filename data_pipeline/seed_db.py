#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from magic_formula.db.repository import get_repository
from magic_formula.services.mappers import to_balance_sheet, to_daily_price, to_income_statement, to_instruments, to_ratios

PIPELINE_DIR = Path(__file__).resolve().parent
SYMBOLS_FILE = PIPELINE_DIR / "nse_stocks.csv"
SEED_FILE = PIPELINE_DIR / "stock_data_master_seed.csv"


def main() -> None:
    repo = get_repository()
    repo.init_schema()
    print(f"DB: {repo.db_path}")

    if SYMBOLS_FILE.exists():
        df = pd.read_csv(SYMBOLS_FILE, dtype=str).fillna("")
        # normalize header
        rows = to_instruments(df)
        n = repo.upsert_instruments(rows)
        print(f"Upserted {n} instruments from nse_stocks.csv")
        # Also patch sc_id mapping from seed where available: seed has sc_id vs SYMBOL mismatches
        try:
            seed = pd.read_csv(SEED_FILE, dtype=str, nrows=5000).fillna("")
            # seed columns include sc_id, stock_name, name, but not SYMBOL direct; we can map via stock_name fuzzy later
            # For now, also upsert company_profile from seed's sc_sector etc.
        except Exception as e:
            print(f"Seed scan skipped: {e}")

    if not SEED_FILE.exists():
        print(f"No seed file at {SEED_FILE}")
        return

    seed = pd.read_csv(SEED_FILE, dtype=str).fillna("")
    print(f"Seed rows: {len(seed)}")
    # Need mapping SYMBOL <-> seed row: seed has stock_name but not SYMBOL; we infer via name or sc_id lookup
    # Build map name->symbol from instruments
    name_to_symbol = {}
    try:
        cur = repo._conn.execute("SELECT symbol, name FROM instruments").fetchall()
        for r in cur:
            name_to_symbol[str(r[1]).lower().strip()] = r[0]
    except Exception:
        pass

    # Also map sc_id -> symbol from instruments if seed provides sc_id
    scid_to_symbol = {}
    try:
        cur = repo._conn.execute("SELECT symbol, sc_id FROM instruments WHERE sc_id IS NOT NULL").fetchall()
        for r in cur:
            if r[1]:
                scid_to_symbol[str(r[1]).strip().upper()] = r[0]
    except Exception:
        pass

    trade_date = dt.date.today().isoformat()
    period_end = trade_date

    # Pre-collect missing symbols to ensure FK satisfied: ensure every pdt symbol exists as instrument
    existing_symbols = {r[0] for r in repo._conn.execute("SELECT symbol FROM instruments").fetchall()}
    missing_instruments: list[dict[str, str]] = []
    seen_missing = set()
    for _, rec in seed.iterrows():
        recd = rec.to_dict()
        pdt = str(recd.get("pdt_dis_nm", ""))
        parts = [p.strip() for p in pdt.split(",")]
        if len(parts) >= 2:
            cand = parts[1].strip().upper()
            if cand and len(cand) <= 12 and cand not in existing_symbols and cand not in seen_missing:
                # Only create if cand looks like NSE symbol (letters/numbers)
                if cand.replace("_", "").replace("-", "").isalnum():
                    missing_instruments.append({"symbol": cand, "name": str(recd.get("name", "")).strip(), "sc_id": str(recd.get("sc_id", "")).strip().upper()})
                    seen_missing.add(cand)
    if missing_instruments:
        repo.upsert_instruments(missing_instruments)
        print(f"Upserted {len(missing_instruments)} missing instruments from seed")
        repo._conn.commit()
        # refresh name maps
        name_to_symbol = {}
        for r in repo._conn.execute("SELECT symbol, name FROM instruments").fetchall():
            name_to_symbol[str(r[1]).lower().strip()] = r[0]
        scid_to_symbol = {}
        for r in repo._conn.execute("SELECT symbol, sc_id FROM instruments WHERE sc_id IS NOT NULL").fetchall():
            if r[1]:
                scid_to_symbol[str(r[1]).strip().upper()] = r[0]

    daily_rows = []
    inc_rows = []
    bs_rows = []
    ratio_rows = []
    skipped = 0
    for _, rec in seed.iterrows():
        recd = rec.to_dict()
        sc_id = str(recd.get("sc_id", "")).strip().upper()
        name = str(recd.get("name", "")).strip()
        symbol = scid_to_symbol.get(sc_id) or name_to_symbol.get(name.lower())
        if not symbol:
            pdt = str(recd.get("pdt_dis_nm", ""))
            parts = [p.strip() for p in pdt.split(",")]
            if len(parts) >= 2:
                cand = parts[1].strip().upper()
                if cand and len(cand) <= 12:
                    symbol = cand
        if not symbol:
            skipped += 1
            continue
        if sc_id:
            try:
                repo._conn.execute("UPDATE instruments SET sc_id=? WHERE symbol=? AND (sc_id IS NULL OR sc_id='')", (sc_id, symbol))
            except Exception:
                pass
        # also ensure instrument exists (FK)
        if symbol not in existing_symbols and symbol not in seen_missing:
            try:
                repo._conn.execute("INSERT OR IGNORE INTO instruments(symbol, name, sc_id) VALUES (?, ?, ?)", (symbol, name, sc_id))
            except Exception:
                pass
        daily_rows.append(to_daily_price(symbol, recd, trade_date))
        inc_rows.append(to_income_statement(symbol, recd, period_end))
        bs_rows.append(to_balance_sheet(symbol, recd, period_end))
        ratio_rows.append(to_ratios(symbol, recd, period_end))

    repo._conn.commit()
    print(f"Daily/Income/BS/Ratios prepared: {len(daily_rows)} rows, skipped {skipped}")

    if daily_rows:
        repo.upsert_daily_prices(daily_rows)
        print(f"Upserted daily_prices {len(daily_rows)}")
    if inc_rows:
        repo.upsert_income_statement(inc_rows)
        repo.upsert_balance_sheet(bs_rows)
        repo.upsert_ratios(ratio_rows)
        print(f"Upserted income {len(inc_rows)} balance {len(bs_rows)} ratios {len(ratio_rows)}")

    profile_rows = []
    valid_symbols = {r[0] for r in repo._conn.execute("SELECT symbol FROM instruments").fetchall()}
    for _, rec in seed.iterrows():
        recd = rec.to_dict()
        sc_id = str(recd.get("sc_id", "")).strip().upper()
        name = str(recd.get("name", "")).strip()
        symbol = scid_to_symbol.get(sc_id) or name_to_symbol.get(name.lower())
        if not symbol:
            pdt = str(recd.get("pdt_dis_nm", ""))
            parts = [p.strip() for p in pdt.split(",")]
            if len(parts) >= 2:
                symbol = parts[1].strip().upper()
        if not symbol or symbol not in valid_symbols:
            continue
        profile_rows.append(
            {
                "symbol": symbol,
                "sc_sector_id": recd.get("sc_sector_id"),
                "sc_sector": recd.get("sc_sector"),
                "industry": recd.get("sc_sector"),
                "link_src": recd.get("link_src"),
                "pdt_dis_nm": recd.get("pdt_dis_nm"),
            }
        )
    try:
        repo.upsert_company_profile(profile_rows)
        print(f"Upserted company_profile {len(profile_rows)}")
    except Exception as e:
        print(f"company_profile upsert warn: {e}")

    repo._conn.commit()
    print("Seed DB done")


if __name__ == "__main__":
    main()
