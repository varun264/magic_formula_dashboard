from __future__ import annotations

import datetime as dt
import re
from typing import List

import requests

from .base import CalendarEvent
from .mcp_client import MCPSearchClient


class BSESource:
    source_name = "BSE"
    priority = 2

    def __init__(self, mcp_client: MCPSearchClient | None = None) -> None:
        self.mcp = mcp_client or MCPSearchClient()

    def fetch(self, target_date: dt.date) -> List[CalendarEvent]:
        events: List[CalendarEvent] = []
        # Use the query pattern proven to return BSE table with excerpts (via Parallel)
        # Objective with multiple search_queries yields BSE Forth_Results page with pipe table
        objective = f"Find companies with results scheduled on {target_date.isoformat()} from BSE forthcoming results calendar and Moneycontrol results calendar"
        queries = [
            f"BSE forthcoming results calendar {target_date.strftime('%d %b %Y')}",
            f"BSE results calendar {target_date.isoformat()}",
            f"Moneycontrol results calendar {target_date.strftime('%d %b %Y')}",
        ]
        try:
            # Directly call mcp search with crafted objective via internal method to control queries
            import uuid

            sid = getattr(self.mcp, "_session_id", str(uuid.uuid4()))
            self.mcp._session_id = sid  # type: ignore
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "web_search",
                    "arguments": {
                        "objective": objective,
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
            # Parse results from parallel response
            import json

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
                # Try to parse BSE pipe table from snippet
                cands = self._parse_bse_table(snippet, target_date, url)
                if cands:
                    events.extend(cands)
                # Also try full fetch for BSE/MC pages that contain table (snippet may be truncated)
                if "bseindia.com" in url.lower() or "moneycontrol.com" in url.lower():
                    txt = self.mcp.fetch(url) or ""
                    c2 = self._parse_bse_table(txt, target_date, url)
                    if c2:
                        events.extend(c2)
                # Generic concall/trendlyne table (e.g., concall.in earnings calendar)
                if "concall.in" in url.lower() or "trendlyne" in url.lower():
                    c3 = self._parse_concall_table(snippet + " " + (self.mcp.fetch(url) or ""), target_date, url)
                    if c3:
                        events.extend(c3)
        except Exception:
            pass
        if not events:
            # Fallback to original simple search
            try:
                results = self.mcp.search(f"BSE results {target_date.strftime('%d %b %Y')}", limit=5)
                for r in results:
                    events.extend(self._parse_bse_table(r.snippet or "", target_date, r.url))
                    events.extend(self._parse_concall_table(r.snippet or "", target_date, r.url))
            except Exception:
                pass
        seen = {}
        for e in events:
            if e.symbol not in seen:
                seen[e.symbol] = e
        return list(seen.values())

    def _parse_bse_table(self, text: str, target_date: dt.date, url: str) -> List[CalendarEvent]:
        if not text or "|" not in text:
            return []
        candidates: List[CalendarEvent] = []
        # BSE table: |Security Code |Security Name |Result Date |
        #            |514348 |WINSOME |29 Aug 2026 |
        target_str_variants = {
            target_date.strftime("%d %b %Y").lower(),  # 29 Aug 2026
            target_date.strftime("%d %b %Y").replace(" 0", " ").lower(),
            target_date.strftime("%d-%b-%Y").lower(),
            target_date.strftime("%d/%m/%Y"),
            target_date.isoformat(),
        }
        # Also handle "01 Sept 2026" vs "01 Sep 2026"
        sept_variants = set()
        for v in list(target_str_variants):
            sept_variants.add(v.replace("sep", "sept"))
            sept_variants.add(v.replace("sept", "sep"))
        target_str_variants |= sept_variants

        for line in text.splitlines():
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|") if p.strip()]
            if len(parts) < 3:
                continue
            # parts should be [code, name, date] or header
            if parts[0].lower().startswith("security code") or parts[0].lower().startswith("security"):
                continue
            code, name, date_str = parts[0], parts[1], parts[2]
            if not re.match(r"^\d{4,6}$", code):
                # sometimes name is code, handle swapped
                if re.match(r"^[A-Z0-9]{3,12}$", code) and re.match(r"^\d{1,2} \w+ \d{4}$", date_str):
                    name = code
                    date_str = parts[2] if len(parts) > 2 else ""
                else:
                    continue
            if date_str.lower() not in target_str_variants and not any(v in date_str.lower() for v in target_str_variants):
                # Check if date_str equals target
                try:
                    # Normalize date_str like "29 Aug 2026" or "01 Sept 2026"
                    d = date_str.replace("Sept", "Sep")
                    parsed = dt.datetime.strptime(d, "%d %b %Y").date()
                    if parsed != target_date:
                        continue
                except Exception:
                    continue
            sym = name.upper().strip()
            # BSE names may be like "WINSOME", need to validate not garbage
            if len(sym) < 2 or len(sym) > 12 or sym in {"SECURITY", "CODE", "NAME", "RESULT", "DATE"}:
                continue
            # Filter non-symbol words
            if re.match(r"^[A-Z0-9]+$", sym) and not sym.isdigit():
                candidates.append(CalendarEvent(symbol=sym, event_date=target_date.isoformat(), source="BSE", source_url=url, confidence=0.85, result_type="quarterly"))
        return candidates

    def _parse_concall_table(self, text: str, target_date: dt.date, url: str) -> List[CalendarEvent]:
        if not text or "Sep" not in text and "Aug" not in text:
            return []
        candidates: List[CalendarEvent] = []
        # Concall format: ### 2 Sep (Today) ### Technocraft Ventures
        # Find section for target date
        target_day = target_date.day
        target_mon = target_date.strftime("%b")  # Sep
        # Look for pattern like "### 2 Sep"
        import re as _re

        # Split by "###"
        parts = text.split("###")
        in_target_section = False
        for part in parts:
            p = part.strip()
            if not p:
                continue
            # Check if this part is a date header
            if _re.match(rf"^\s*{target_day}\s+{target_mon}", p, _re.IGNORECASE) or _re.match(rf"^{target_day}\s+{target_mon}", p.strip(), _re.IGNORECASE):
                in_target_section = True
                continue
            # If we see next date header (e.g., "4 Sep" or "7 Sep"), exit section
            if _re.match(r"^\s*\d{1,2}\s+[A-Za-z]{3}", p) and in_target_section:
                # This is next date, break
                break
            if in_target_section:
                # This is a company name in target date section
                # Clean: remove trailing "EPS ..." etc, take first 2-3 words
                # Example "Technocraft Ventures ### Vivanta Industries EPS  +100%" already split
                # So p is "Technocraft Ventures" or "Vivanta Industries EPS  +100%"
                # Extract company name: take up to 3 words before EPS
                name = p.split("EPS")[0].strip()
                # Remove special chars, keep letters & spaces
                name = _re.sub(r"[^A-Za-z &]", "", name).strip()
                if len(name) < 3 or len(name) > 40:
                    continue
                # Convert to symbol-like: uppercase, take as symbol? For NSE, need symbol not name.
                # We'll try to map name to symbol later via known universe; for now use uppercased name token
                # Extract first word or known symbol pattern
                # For Technocraft Ventures, NSE symbol might be TECHNOCRAF etc; we can emit as name and let discovery filter via name->symbol mapping
                # Emit as symbol using first word uppercased? Better to emit as discovered name and let later mapping handle
                sym_guess = name.upper().replace(" ", "")[:12]
                # Filter obvious non-companies
                if sym_guess in {"SECTOR", "COMPANIES", "FILTER", "RESULTS"}:
                    continue
                candidates.append(CalendarEvent(symbol=sym_guess, event_date=target_date.isoformat(), source="BSE", source_url=url, confidence=0.6, result_type="quarterly"))
                if len(candidates) >= 20:
                    break
        return candidates

    def _parse_text_fallback(self, text: str, target_date: dt.date, url: str) -> List[CalendarEvent]:
        if "Result Date" not in text:
            return []
        return self._parse_bse_table(text, target_date, url)
