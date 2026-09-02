from __future__ import annotations

import datetime as dt
import re
from typing import List

import requests
from bs4 import BeautifulSoup

from .base import CalendarEvent
from .mcp_client import MCPSearchClient


class MCSource:
    source_name = "MC"
    priority = 1

    def __init__(self, mcp_client: MCPSearchClient | None = None) -> None:
        self.mcp = mcp_client or MCPSearchClient()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.moneycontrol.com/",
            }
        )

    def fetch(self, target_date: dt.date) -> List[CalendarEvent]:
        events: List[CalendarEvent] = []
        # Try MCP search with snippets that contain calendar tables
        queries = [
            f"Moneycontrol results calendar {target_date.isoformat()} site:moneycontrol.com",
            f"Moneycontrol earnings calendar {target_date.strftime('%d %b %Y')}",
        ]
        for query in queries:
            try:
                results = self.mcp.search(query, limit=5)
                for r in results:
                    # Try snippet first (often contains table)
                    cands = self._parse_bse_table(r.snippet or "", target_date, r.url)
                    if cands:
                        events.extend(cands)
                    if "moneycontrol.com" in r.url:
                        text = self.mcp.fetch(r.url) or ""
                        cands2 = self._parse_bse_table(text, target_date, r.url)
                        if cands2:
                            events.extend(cands2)
                        else:
                            # fallback generic
                            events.extend(self._parse_text(text, target_date, r.url))
                if events:
                    break
            except Exception:
                continue
        if not events:
            try:
                return self._fetch_direct(target_date)
            except Exception:
                return []
        # dedupe
        seen = {}
        for e in events:
            if e.symbol not in seen:
                seen[e.symbol] = e
        return list(seen.values())

    def _parse_bse_table(self, text: str, target_date: dt.date, url: str) -> List[CalendarEvent]:
        if not text or "|" not in text:
            return []
        candidates: List[CalendarEvent] = []
        target_str_variants = {
            target_date.strftime("%d %b %Y").lower(),
            target_date.strftime("%d %b %Y").replace(" 0", " ").lower(),
            target_date.isoformat(),
        }
        target_str_variants |= {v.replace("sep", "sept") for v in list(target_str_variants)}
        target_str_variants |= {v.replace("sept", "sep") for v in list(target_str_variants)}
        for line in text.splitlines():
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 3:
                continue
            if parts[0].lower().startswith("security"):
                continue
            code, name, date_str = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
            try:
                d = date_str.replace("Sept", "Sep")
                parsed = dt.datetime.strptime(d, "%d %b %Y").date()
                if parsed != target_date:
                    continue
            except Exception:
                if date_str.lower() not in target_str_variants:
                    continue
            sym = name.upper().strip()
            if len(sym) < 2 or len(sym) > 12 or sym in {"SECURITY", "CODE"}:
                continue
            if re.match(r"^[A-Z0-9]+$", sym) and not sym.isdigit():
                candidates.append(CalendarEvent(symbol=sym, event_date=target_date.isoformat(), source="MC", source_url=url, confidence=0.75))
        return candidates

    def _fetch_direct(self, target_date: dt.date) -> List[CalendarEvent]:
        url = "https://www.moneycontrol.com/stocks/earnings/"
        try:
            resp = self.session.get(url, timeout=10)
            if not resp.ok:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            text = soup.get_text(separator=" ", strip=True)
            # Try table parse first
            cands = self._parse_bse_table(resp.text, target_date, url)
            if cands:
                return cands
            return self._parse_text(text, target_date, url)
        except Exception:
            return []

    def _parse_text(self, text: str, target_date: dt.date, url: str) -> List[CalendarEvent]:
        # Conservative fallback: do not emit garbage; return empty to avoid false positives
        # Only emit if we find date string with strong signal
        date_str = target_date.strftime("%d %b")
        if date_str.lower() not in text.lower() and target_date.isoformat() not in text:
            return []
        candidates: List[CalendarEvent] = []
        idx = text.lower().find(date_str.lower())
        window = text[max(0, idx - 1000) : idx + 2000] if idx != -1 else text[:3000]
        # Look for pipe table in window
        candidates = self._parse_bse_table(window, target_date, url)
        return candidates
