from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd


@dataclass(frozen=True)
class TickerInfo:
    """Canonical metadata for a Moneycontrol ticker search result."""

    stock_id: str
    stock_name: str
    link_src: str
    raw: Dict[str, Any]


@dataclass(frozen=True)
class ScrapedStock:
    """Container for a fully scraped stock record."""

    ticker: TickerInfo
    overview: Dict[str, Any]
    profit_loss: Dict[str, Any]
    quarter_results: Dict[str, Any]
    ratios: Dict[str, Any]

    def to_record(self) -> Dict[str, Any]:
        """Merge all collected attributes into a flat dictionary."""
        record: Dict[str, Any] = dict(self.ticker.raw)
        record.update(self.overview)
        record.update(self.profit_loss)
        record.update(self.quarter_results)
        record.update(self.ratios)

        def numeric(value: Any) -> pd.Series | float:
            return pd.to_numeric(str(value).replace(",", ""), errors="coerce")

        ebit_cr = numeric(record.get("Annual EBIT (Cr.)"))
        interest_cr = numeric(record.get("Annual Interest (Cr.)"))
        net_profit_cr = numeric(record.get("Annual Net Profit (Cr.)"))
        sales_cr = numeric(record.get("Annual Sales (Cr.)"))
        market_cap_cr = numeric(record.get("MKTCAP", record.get("Mkt Cap (Rs. Cr.)")))
        previous_close = numeric(record.get("Previous Close"))
        book_value_per_share = numeric(record.get("Book Value Per Share"))

        if pd.notna(ebit_cr) and pd.notna(market_cap_cr) and pd.notna(previous_close) and market_cap_cr > 0:
            record.setdefault("PBIT/Share (Rs.)", (ebit_cr * previous_close) / market_cap_cr)

        if pd.notna(market_cap_cr):
            record.setdefault("Enterprise Value (Cr.)", market_cap_cr)

        def per_share(value_cr: pd.Series | float) -> pd.Series | float:
            return (value_cr * previous_close) / market_cap_cr

        if (
            pd.notna(net_profit_cr)
            and pd.notna(market_cap_cr)
            and pd.notna(previous_close)
            and market_cap_cr > 0
        ):
            np_share = per_share(net_profit_cr)
            record.setdefault("Net Profit/Share (Rs.)", np_share)
            if pd.notna(sales_cr) and sales_cr > 0:
                record.setdefault("Net Profit Margin (%)", (net_profit_cr / sales_cr) * 100)
                record.setdefault("Revenue From Operations/Share (Rs.)", per_share(sales_cr))

        if pd.notna(sales_cr) and pd.notna(market_cap_cr) and pd.notna(previous_close) and market_cap_cr > 0:
            record.setdefault("Revenue From Operations/Share (Rs.)", per_share(sales_cr))

        if (
            pd.notna(ebit_cr)
            and pd.notna(interest_cr)
            and pd.notna(market_cap_cr)
            and pd.notna(previous_close)
            and market_cap_cr > 0
        ):
            if interest_cr > 0:
                record.setdefault("Interest Coverage (X)", ebit_cr / interest_cr)
            pbt_share = per_share(ebit_cr - interest_cr)
            if pbt_share == pbt_share:  # NaN guard
                record.setdefault("PBT/Share (Rs.)", pbt_share)

        if (
            pd.notna(ebit_cr)
            and pd.notna(market_cap_cr)
            and pd.notna(previous_close)
            and pd.notna(book_value_per_share)
            and book_value_per_share > 0
        ):
            equity_cr = (book_value_per_share * market_cap_cr) / previous_close
            if equity_cr > 0:
                record.setdefault("Return on Capital Employed (%)", (ebit_cr / equity_cr) * 100)

        column_to_drop = f"Key Financial Ratios of {self.ticker.stock_name}(in Rs. Cr.)"
        record.pop(column_to_drop, None)
        return record
