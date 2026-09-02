from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Dict

import pandas as pd


def _num(v: Any) -> float | None:
    if v is None or v == "" or v == "--":
        return None
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def record_source_hash(record: Dict[str, Any]) -> str:
    payload = json.dumps({k: str(v) for k, v in sorted(record.items())}, sort_keys=True)
    return hashlib.md5(payload.encode()).hexdigest()[:12]


def to_instruments(symbols_df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, r in symbols_df.iterrows():
        rows.append(
            {
                "symbol": str(r.get("SYMBOL", "")).strip().upper(),
                "name": str(r.get("NAME OF COMPANY", "")).strip(),
                "isin": str(r.get("ISIN NUMBER", "")).strip(),
                "isin_number": str(r.get("ISIN NUMBER", "")).strip(),
                "series": str(r.get("SERIES", "")).strip(),
                "face_value": _num(r.get("FACE VALUE")),
                "listing_date": str(r.get("DATE OF LISTING", "")).strip() or None,
            }
        )
    return rows


def to_daily_price(symbol: str, record: Dict[str, Any], trade_date: str | None = None) -> dict[str, Any]:
    if trade_date is None:
        trade_date = dt.date.today().isoformat()
    return {
        "symbol": symbol.upper().strip(),
        "trade_date": trade_date,
        "close": _num(record.get("Previous Close")),
        "market_cap_cr": _num(record.get("Mkt Cap (Rs. Cr.)") or record.get("MKTCAP")),
        "pe_ttm": _num(record.get("TTM PE")),
        "pb": _num(record.get("Price/BV (X)") or record.get("Price To Book Value (X)")),
        "dividend_yield": _num(record.get("Dividend Yield (%)")),
        "volume": None,
        "source": "moneycontrol",
        "source_hash": record_source_hash({k: record.get(k) for k in ["Previous Close", "Mkt Cap (Rs. Cr.)", "MKTCAP", "TTM PE"]}),
    }


def to_company_profile(symbol: str, record: Dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol.upper().strip(),
        "sc_sector_id": record.get("sc_sector_id") or record.get("sc_sector"),
        "sc_sector": record.get("sc_sector"),
        "industry": record.get("sc_sector"),
        "link_src": record.get("link_src"),
        "pdt_dis_nm": record.get("pdt_dis_nm"),
    }


def to_income_statement(symbol: str, record: Dict[str, Any], period_end: str | None = None) -> dict[str, Any]:
    if period_end is None:
        period_end = dt.date.today().isoformat()
    try:
        cal_year = dt.date.fromisoformat(period_end).year
    except Exception:
        cal_year = dt.date.today().year
    # Try primary annual columns, fallback to per-share reconstruction from seed
    mcap = _num(record.get("Mkt Cap (Rs. Cr.)") or record.get("MKTCAP"))
    close = _num(record.get("Previous Close"))
    def reconstruct_per_share(value_share_key: str) -> float | None:
        v = _num(record.get(value_share_key))
        if v is not None and mcap and close and mcap != 0 and close != 0:
            try:
                return (v * mcap * 1e7) / (close * 1e7) * 1e7  # v * shares -> but need Cr.
                # Actually value_cr = value_share * shares, shares = mcap*1e7/close, value_cr in Rs = value_share*shares
                # Convert Rs to Cr: /1e7
            except Exception:
                return None
        return None

    # Correct reconstruction: value_cr = value_share * market_cap_cr *1e7 / previous_close /1e7 = value_share * mcap / close
    def share_to_cr(share_val: float | None) -> float | None:
        if share_val is not None and mcap and close and close != 0:
            try:
                return (share_val * mcap) / close
            except Exception:
                return None
        return None

    pbit_share = _num(record.get("PBIT/Share (Rs.)"))
    rev_share = _num(record.get("Revenue from Operations/Share (Rs.)") or record.get("Operating Revenue Per Share"))
    np_share = _num(record.get("Net Profit/Share (Rs.)"))
    ebit_cr = _num(record.get("Annual EBIT (Cr.)"))
    if ebit_cr is None and pbit_share is not None:
        ebit_cr = share_to_cr(pbit_share)
    revenue_cr = _num(record.get("Annual Sales (Cr.)"))
    if revenue_cr is None and rev_share is not None:
        revenue_cr = share_to_cr(rev_share)
    net_profit_cr = _num(record.get("Annual Net Profit (Cr.)"))
    if net_profit_cr is None and np_share is not None:
        net_profit_cr = share_to_cr(np_share)
    interest_cr = _num(record.get("Annual Interest (Cr.)"))
    # if still none, try interest from PBT share diff: PBIT - PBT approx interest
    if interest_cr is None:
        pbt_share = _num(record.get("PBT/Share (Rs.)"))
        if pbit_share is not None and pbt_share is not None:
            interest_cr = share_to_cr(pbit_share - pbt_share) if (pbit_share - pbt_share) != 0 else None

    return {
        "symbol": symbol.upper().strip(),
        "period_end": period_end,
        "period": "FY",
        "consolidation_basis": "consolidated",
        "calendar_year": cal_year,
        "revenue_cr": revenue_cr,
        "ebit_cr": ebit_cr,
        "interest_cr": interest_cr,
        "net_profit_cr": net_profit_cr,
        "eps_basic": _num(record.get("Basic EPS (Rs.)")),
        "eps_diluted": _num(record.get("Diluted EPS (Rs.)")),
        "cash_eps": _num(record.get("Cash EPS (Rs.)")),
        "filing_date": None,
        "source_hash": record_source_hash({k: record.get(k) for k in ["Annual EBIT (Cr.)", "PBIT/Share (Rs.)", "Annual Sales (Cr.)"]}),
    }


def to_balance_sheet(symbol: str, record: Dict[str, Any], period_end: str | None = None) -> dict[str, Any]:
    if period_end is None:
        period_end = dt.date.today().isoformat()
    bvps = _num(record.get("Book Value [ExclRevalReserve]/Share (Rs.)") or record.get("Book Value [InclRevalReserve]/Share (Rs.)") or record.get("Book Value Per Share"))
    mcap = _num(record.get("Mkt Cap (Rs. Cr.)") or record.get("MKTCAP"))
    close = _num(record.get("Previous Close"))
    shares_out = None
    equity_cr = None
    if bvps and mcap and close and close != 0:
        try:
            equity_cr = (bvps * mcap) / close
            shares_out = int((mcap * 1e7) / close) if close else None
        except Exception:
            pass
    return {
        "symbol": symbol.upper().strip(),
        "period_end": period_end,
        "period": "FY",
        "consolidation_basis": "consolidated",
        "total_assets_cr": None,
        "total_debt_cr": None,
        "cash_and_equivalents_cr": None,
        "equity_cr": equity_cr,
        "book_value_per_share": bvps,
        "shares_outstanding": shares_out,
        "source_hash": record_source_hash({"BVPS": bvps, "equity": equity_cr}),
    }


def to_ratios(symbol: str, record: Dict[str, Any], period_end: str | None = None) -> dict[str, Any]:
    if period_end is None:
        period_end = dt.date.today().isoformat()
    return {
        "symbol": symbol.upper().strip(),
        "period_end": period_end,
        "period": "FY",
        "consolidation_basis": "consolidated",
        "roe_pct": _num(record.get("Return on Networth/Equity (%)") or record.get("Return On Equity/Networth (%)")),
        "roce_pct": _num(record.get("Return on Capital Employed (%)") or record.get("ROCE (%)")),
        "roa_pct": _num(record.get("Return on Assets (%)") or record.get("Return On Assets (%)")),
        "debt_equity": _num(record.get("Total Debt/Equity (X)")),
        "current_ratio": _num(record.get("Current Ratio (X)")),
        "quick_ratio": _num(record.get("Quick Ratio (X)")),
        "interest_coverage": _num(record.get("Interest Coverage Ratios (%)") or record.get("Interest Coverage (X)")),
        "asset_turnover": _num(record.get("Asset Turnover Ratio (%)")),
        "dividend_yield": _num(record.get("Dividend Yield (%)")),
        "payout_ratio": _num(record.get("Dividend Payout Ratio (NP) (%)")),
        "retention_ratio": _num(record.get("Earnings Retention Ratio (%)")),
        "pb": _num(record.get("Price/BV (X)") or record.get("Price To Book Value (X)")),
        "pe": _num(record.get("TTM PE")),
        "source_hash": record_source_hash({k: record.get(k) for k in ["Return on Capital Employed (%)", "Total Debt/Equity (X)"]}),
    }
