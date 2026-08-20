from __future__ import annotations

import json
from typing import Any, Dict

from bs4 import BeautifulSoup


class ProfitLossParser:
    """Extract the latest annual EBIT from the Moneycontrol profit-loss page."""

    def parse(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if script is None or not script.string:
            return {}

        payload = json.loads(script.string)
        performance = payload.get("props", {}).get("pageProps", {}).get("data", {}).get("performance", {})
        annual_sections = performance.get("list", []) if isinstance(performance, dict) else []

        for section in annual_sections:
            if section.get("l1_heading") != "Annual":
                continue
            for row in section.get("l1_list", []):
                if row.get("l2_heading") != "EBIT":
                    continue
                values = [item.get("value") for item in row.get("l2_list", []) if item.get("value") not in (None, "")]
                if values:
                    return {"Annual EBIT (Cr.)": values[0]}
        return {}
