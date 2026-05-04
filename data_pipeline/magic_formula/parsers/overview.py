from __future__ import annotations

from typing import Any, Dict

from bs4 import BeautifulSoup


class OverviewParser:
    """Extract headline metrics from the Moneycontrol overview page."""

    ELEMENT_MAP = {
        "Mkt Cap (Rs. Cr.)": ("td", {"class": "nsemktcap bsemktcap"}),
        "Previous Close": ("td", {"class": "nseprvclose bseprvclose"}),
        "Face Value": ("td", {"class": "nsefv bsefv"}),
        "TTM EPS": ("span", {"class": "nseceps bseceps"}),
        "TTM PE": ("span", {"class": "nsepe bsepe"}),
        "Book Value Per Share": ("td", {"class": "nsebv bsebv"}),
    }

    def parse(self, html: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        data: Dict[str, Any] = {}

        for key, (tag, attrs) in self.ELEMENT_MAP.items():
            element = soup.find(tag, attrs=attrs)
            if element is not None:
                data[key] = element.get_text(strip=True)
        return data
