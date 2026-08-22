from __future__ import annotations

import json
from typing import Any, Dict

from bs4 import BeautifulSoup


class RatiosParser:
    """Extract the latest financial ratios from the Moneycontrol ratios page."""

    def parse(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            return {}

        payload = json.loads(script.string)
        stock_info = payload.get("props", {}).get("pageProps", {}).get("data", {}).get("stockInfo", {})
        if not isinstance(stock_info, dict):
            return {}

        ratios: Dict[str, Any] = {}

        def pick(*keys: str) -> Any:
            for key in keys:
                value = stock_info.get(key)
                if value not in (None, "", "-"):
                    return value
            return None

        selected = {
            "TTM EPS": pick("sc_ttm_cons", "SC_TTM"),
            "Cash EPS (Rs.)": pick("CEPS"),
            "TTM PE": pick("PECONS", "PE"),
            "Book Value [ExclRevalReserve]/Share (Rs.)": pick("BV"),
            "Book Value [InclRevalReserve]/Share (Rs.)": pick("BVCONS"),
            "Price/BV (X)": pick("PB"),
            "Price To Book Value (X)": pick("PBCONS"),
            "Dividend Yield (%)": pick("DYCONS", "DY"),
            "Face Value": pick("FV"),
        }

        for key, value in selected.items():
            if value is not None:
                ratios[key] = value

        return ratios
