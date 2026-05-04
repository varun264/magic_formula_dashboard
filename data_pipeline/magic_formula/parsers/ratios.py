from __future__ import annotations

from typing import Dict

from bs4 import BeautifulSoup


class RatiosParser:
    """Extract the latest financial ratios from the Moneycontrol ratios page."""

    def parse(self, html: str) -> Dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        ratios: Dict[str, str] = {}

        for row in soup.find_all("tr"):
            columns = row.find_all("td")
            if len(columns) < 2:
                continue
            name = columns[0].get_text(strip=True)
            value = columns[1].get_text(strip=True)
            if name and value:
                ratios[name] = value
        return ratios
