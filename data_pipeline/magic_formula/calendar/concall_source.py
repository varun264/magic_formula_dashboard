from __future__ import annotations

import datetime as dt
import re
from typing import List

from .base import CalendarEvent
from .mcp_client import MCPSearchClient


class ConcallSource:
    source_name = "CONCALL"
    priority = 2

    def __init__(self, mcp_client: MCPSearchClient | None = None) -> None:
        self.mcp = mcp_client or MCPSearchClient()

    def fetch(self, target_date: dt.date) -> List[CalendarEvent]:
        events: List[CalendarEvent] = []
        # Concall and Trendlyne are more reliable than BSE JS page
        queries = [
            f"concall earnings calendar {target_date.strftime('%d %b %Y')}",
            f"trendlyne upcoming results {target_date.strftime('%d %b %Y')}",
            f"earnings calendar {target_date.strftime('%d %b')}",
        ]
        try:
            # Use parallel web_search with concall-focused objective
            import uuid, json

            sid = getattr(self.mcp, "_session_id", str(uuid.uuid4()))
            self.mcp._session_id = sid  # type: ignore
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "web_search",
                    "arguments": {
                        "objective": f"Find companies declaring results on {target_date.isoformat()} from concall and trendlyne earnings calendars",
                        "search_queries": queries,
                        "session_id": sid,
                        "model_name": "muse-spark-1.2",
                    },
                },
            }
            headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
            resp = self.mcp.session.post(self.mcp.MCP_SERVERS[0]["url"], json=payload, headers=headers, timeout=self.mcp.timeout)
            resp.raise_for_status()
            data = self.mcp._parse_mcp_response(resp.text)
            content = data.get("result", {}).get("content", [])
            inner = {}
            if content and isinstance(content[0].get("text"), str):
                try:
                    inner = json.loads(content[0]["text"])
                except Exception:
                    inner = {}
            for r in inner.get("results", [])[:10]:
                url = r.get("url", "")
                excerpts = r.get("excerpts") or []
                snippet = " ".join(excerpts) if excerpts else ""
                # Try concall/trendlyne table parsing
                if "concall.in" in url.lower() or "trendlyne" in url.lower():
                    cands = self._parse_concall_snippet(snippet, target_date, url)
                    if cands:
                        events.extend(cands)
                    # Also try fetching full page for more complete calendar
                    txt = self.mcp.fetch(url) or ""
                    c2 = self._parse_concall_snippet(txt, target_date, url)
                    if c2:
                        events.extend(c2)
                # Generic BSE-like table also possible in concall page
                cands2 = self._parse_concall_snippet(snippet, target_date, url)
                if cands2:
                    events.extend(cands2)
        except Exception:
            pass
        # Fallback simple search
        if not events:
            try:
                results = self.mcp.search(f"concall earnings calendar {target_date.strftime('%d %b %Y')}", limit=3)
                for r in results:
                    events.extend(self._parse_concall_snippet(r.snippet or "", target_date, r.url))
            except Exception:
                pass
        seen = {}
        for e in events:
            if e.symbol not in seen:
                seen[e.symbol] = e
        return list(seen.values())

    def _parse_concall_snippet(self, text: str, target_date: dt.date, url: str) -> List[CalendarEvent]:
        if not text:
            return []
        candidates: List[CalendarEvent] = []
        target_day = target_date.day
        target_mon = target_date.strftime("%b")
        # Normalize Sept -> Sep for matching
        text_norm = text.replace("Sept", "Sep")
        target_mon_norm = target_mon.replace("Sept", "Sep")
        # Split by "###" which concall uses for sections
        if "###" in text:
            parts = text.split("###")
            in_target = False
            for part in parts:
                p = part.strip()
                if not p:
                    continue
                # Date header like "2 Sep (Today)" or "2 Sep" or "4 Sep"
                if re.match(rf"^\s*{target_day}\s+{target_mon_norm}\b", p, re.IGNORECASE):
                    in_target = True
                    continue
                if in_target:
                    # If next date header detected, break
                    if re.match(r"^\s*\d{1,2}\s+[A-Za-z]{3}\b", p):
                        break
                    # Company names: split by "###" already, so each part is a company
                    # Remove suffix like "EPS  +100%" etc.
                    name = p.split("EPS")[0].strip()
                    name = re.sub(r"[^A-Za-z0-9 &]", " ", name).strip()
                    # Take first 3 words as company name
                    words = name.split()
                    if len(words) == 0:
                        continue
                    # Heuristic: company name is 1-4 words, first letter capital
                    comp = " ".join(words[:3])
                    if len(comp) < 3 or len(comp) > 35:
                        continue
                    if comp.upper() in {"SECTOR", "COMPANIES", "FILTER", "RESULTS", "EARNINGS", "CALENDAR"}:
                        continue
                    sym_guess = comp.upper().replace(" ", "").replace("&", "")[:12]
                    # Validate symbol-like
                    if not re.match(r"^[A-Z][A-Z0-9]{2,11}$", sym_guess):
                        continue
                    # Skip generic
                    if sym_guess in {"TODAY", "UPCOMING", "LIVE", "RESULTS"}:
                        continue
                    candidates.append(CalendarEvent(symbol=sym_guess, event_date=target_date.isoformat(), source="CONCALL", source_url=url, confidence=0.7, result_type="quarterly"))
                    if len(candidates) >= 30:
                        break
            if candidates:
                return candidates
        # Fallback: look for trendlyne style pipe table or simple list
        if "|" in text:
            for line in text.splitlines():
                if "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) < 2:
                    continue
                # Check if line contains target date
                if f"{target_day} {target_mon_norm}" not in text and target_date.isoformat() not in text:
                    # Need date in same line or nearby - skip this line if not matching
                    pass
                # Try to extract symbol-like from parts
                for p in parts:
                    if re.match(r"^[A-Z]{3,12}$", p):
                        if p.upper() not in {"SECURITY", "CODE", "RESULT", "DATE"}:
                            candidates.append(CalendarEvent(symbol=p.upper(), event_date=target_date.isoformat(), source="CONCALL", source_url=url, confidence=0.6))
                            break
        return candidates
