from __future__ import annotations

import json
from typing import Any, Dict

from bs4 import BeautifulSoup

OVERVIEW_FIELDS = {
    "revenue": ("Latest Quarter Revenue (Cr.)", "Revenue QoQ (%)", "Revenue YoY (%)"),
    "gross_profit": ("Latest Quarter Gross Profit (Cr.)", None, None),
    "net_profit": ("Latest Quarter Net Profit (Cr.)", "Net Profit QoQ (%)", "Net Profit YoY (%)"),
}


class QuarterlyResultsParser:
    """Extract latest-quarter growth metrics from the Moneycontrol quarterly results page."""

    def parse(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            return {}

        payload = json.loads(script.string)
        performance = payload.get("props", {}).get("pageProps", {}).get("data", {}).get("performance", {})
        overview = performance.get("overview") if isinstance(performance, dict) else None
        if not isinstance(overview, dict):
            return {}

        extracted: Dict[str, Any] = {}
        for key, (value_field, qoq_field, yoy_field) in OVERVIEW_FIELDS.items():
            entry = overview.get(key)
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            if value not in (None, ""):
                extracted[value_field] = value
            if qoq_field and entry.get("qoq") not in (None, ""):
                extracted[qoq_field] = entry["qoq"]
            if yoy_field and entry.get("yoy") not in (None, ""):
                extracted[yoy_field] = entry["yoy"]
        return extracted
