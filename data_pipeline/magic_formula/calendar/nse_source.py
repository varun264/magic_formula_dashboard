from __future__ import annotations

import datetime as dt
import re
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import CalendarEvent
from .mcp_client import MCPSearchClient


class NSESource:
    source_name = "NSE"
    priority = 3

    def __init__(self, mcp_client: MCPSearchClient | None = None) -> None:
        self.mcp = mcp_client or MCPSearchClient()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/html, */*",
            }
        )

    def fetch(self, target_date: dt.date) -> List[CalendarEvent]:
        # Strategy 1: try MCP search for NSE results calendar
        events: List[CalendarEvent] = []
        query = f"NSE results calendar {target_date.isoformat()} site:nseindia.com"
        try:
            results = self.mcp.search(query, limit=5)
            for r in results:
                if "nseindia.com" in r.url:
                    text = self.mcp.fetch(r.url) or ""
                    events.extend(self._parse_text(text, target_date, r.url))
        except Exception:
            pass
        if events:
            return events
        # Strategy 2: direct NSE corporate announcements API (lightweight, no MCP)
        try:
            events = self._fetch_direct_api(target_date)
            if events:
                return events
        except Exception:
            pass
        # Strategy 3: scrape Moneycontrol as proxy (fallback handled by MC source, return empty)
        return []

    def _parse_text(self, text: str, target_date: dt.date, url: str) -> List[CalendarEvent]:
        # Conservative: NSE pages are often JS-rendered; avoid false positives from naive regex.
        # Only extract if we can find a pipe table or NSE-specific listing.
        if not text or "Result" not in text:
            return []
        # Try to parse pipe table if present (similar to BSE)
        candidates: List[CalendarEvent] = []
        if "|" in text:
            target_variants = {
                target_date.strftime("%d %b %Y").lower(),
                target_date.isoformat(),
            }
            target_variants |= {v.replace("sep", "sept") for v in list(target_variants)}
            for line in text.splitlines():
                if "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) < 2:
                    continue
                # Look for symbol-like token and date in same line
                line_lower = line.lower()
                if not any(v in line_lower for v in target_variants):
                    continue
                for p in parts:
                    if re.match(r"^[A-Z]{3,12}$", p) and p.upper() not in {"RESULT", "DATE", "SYMBOL", "COMPANY"}:
                        candidates.append(CalendarEvent(symbol=p.upper(), event_date=target_date.isoformat(), source="NSE", source_url=url, confidence=0.7))
                        break
                if len(candidates) >= 40:
                    break
        return candidates

    def _fetch_direct_api(self, target_date: dt.date) -> List[CalendarEvent]:
        # NSE corporate filings API requires cookies; attempt best-effort
        events: List[CalendarEvent] = []
        try:
            self.session.get("https://www.nseindia.com", timeout=8)
            # Corporate announcements endpoint (may change; failures are ok)
            url = "https://www.nseindia.com/api/corporate-announcements?index=equities"
            resp = self.session.get(url, timeout=8)
            if not resp.ok:
                return []
            data = resp.json()
            for item in data[:100]:
                sym = (item.get("symbol") or "").strip().upper()
                ann = (item.get("subject") or "") + " " + (item.get("desc") or "")
                if not sym or "result" not in ann.lower():
                    continue
                # date filter: check broadcast date equals target_date (approx)
                bdate = item.get("bDate") or item.get("an_dt") or ""
                try:
                    if bdate:
                        # bDate like 01-Jun-2026
                        parsed = dt.datetime.strptime(bdate.split()[0], "%d-%b-%Y").date()
                        if parsed != target_date:
                            continue
                except Exception:
                    pass
                events.append(CalendarEvent(symbol=sym, event_date=target_date.isoformat(), source="NSE", source_url="https://www.nseindia.com", confidence=0.85))
        except Exception:
            return []
        return events
