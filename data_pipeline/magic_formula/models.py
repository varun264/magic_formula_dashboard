from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


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
    ratios: Dict[str, Any]

    def to_record(self) -> Dict[str, Any]:
        """Merge all collected attributes into a flat dictionary."""
        record: Dict[str, Any] = dict(self.ticker.raw)
        record.update(self.overview)
        record.update(self.ratios)

        column_to_drop = f"Key Financial Ratios of {self.ticker.stock_name}(in Rs. Cr.)"
        record.pop(column_to_drop, None)
        return record
