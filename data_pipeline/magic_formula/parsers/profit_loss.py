from __future__ import annotations

import json
from typing import Any, Dict

from bs4 import BeautifulSoup

ROW_FIELDS = {
    "EBIT": "Annual EBIT (Cr.)",
    "Interest": "Annual Interest (Cr.)",
    "Net Profit": "Annual Net Profit (Cr.)",
    "Sales": "Annual Sales (Cr.)",
}


class ProfitLossParser:
    """Extract the latest annual P&L rows from the Moneycontrol profit-loss page."""

    def parse(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            return {}

        payload = json.loads(script.string)
        performance = payload.get("props", {}).get("pageProps", {}).get("data", {}).get("performance", {})
        annual_sections = performance.get("list", []) if isinstance(performance, dict) else []

        extracted: Dict[str, Any] = {}
        for section in annual_sections:
            if section.get("l1_heading") != "Annual":
                continue
            for row in section.get("l1_list", []):
                field = ROW_FIELDS.get(row.get("l2_heading", ""))
                if field is None or field in extracted:
                    continue
                values = [item.get("value") for item in row.get("l2_list", []) if item.get("value") not in (None, "")]
                if values:
                    extracted[field] = values[0]
        return extracted
