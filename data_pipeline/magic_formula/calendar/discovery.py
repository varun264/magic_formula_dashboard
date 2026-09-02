from __future__ import annotations

import datetime as dt
import os
from typing import List

from ..db.repository import SqliteRepository, get_repository
from .base import CalendarEvent
from .bse_source import BSESource
from .concall_source import ConcallSource
from .mcp_client import MCPSearchClient
from .mc_source import MCSource
from .nse_source import NSESource
from .resolver import CalendarResolver


def build_default_resolver(mcp_client: MCPSearchClient | None = None) -> CalendarResolver:
    client = mcp_client or MCPSearchClient()
    return CalendarResolver(
        sources=[
            NSESource(mcp_client=client),
            BSESource(mcp_client=client),
            ConcallSource(mcp_client=client),
            MCSource(mcp_client=client),
        ]
    )


def discover_for_date(target_date: dt.date, resolver: CalendarResolver | None = None) -> List[CalendarEvent]:
    resolver = resolver or build_default_resolver()
    return resolver.discover(target_date)


def discover_tomorrow_and_store(
    repo: SqliteRepository | None = None,
    target_date: dt.date | None = None,
) -> int:
    """
    MCP discovery job: find T+1 events today, store into earnings_calendar.
    Used by cron: run today to queue tomorrow's fundamentals (fetched at T+1+lag).
    """
    if target_date is None:
        target_date = dt.date.today() + dt.timedelta(days=1)
    repo = repo or get_repository()
    repo.init_schema()
    resolver = build_default_resolver()
    events = resolver.discover(target_date)
    # Map to known NSE universe: strict symbol match plus name-based fuzzy
    try:
        known = set(repo.get_instrument_symbols())
        if known:
            # Build name -> symbol map for fuzzy matching (company name contains)
            name_map: dict[str, str] = {}
            try:
                cur = repo._conn.execute("SELECT symbol, name FROM instruments")
                for sym, name in cur.fetchall():
                    if name:
                        # index by upper name without spaces for quick lookup
                        key = name.upper().replace(" ", "").replace("&", "").replace("-", "")[:12]
                        name_map[key] = sym
                        # also by first word
                        first = name.split()[0].upper() if name.split() else ""
                        if first and len(first) >= 3:
                            name_map[first] = sym
            except Exception:
                pass

            filtered: List[CalendarEvent] = []
            for ev in events:
                sym = ev.symbol.upper().strip()
                if sym in known:
                    filtered.append(ev)
                    continue
                # Try name-map for concall style (company name compressed)
                mapped = name_map.get(sym)
                if mapped:
                    filtered.append(CalendarEvent(symbol=mapped, event_date=ev.event_date, source=ev.source, source_url=ev.source_url, confidence=ev.confidence * 0.9, result_type=ev.result_type))
                    continue
                # Try substring match: does any known symbol contain event substring or vice versa?
                for k in known:
                    if sym in k or k in sym:
                        if len(sym) >= 4 and len(k) >= 4:
                            filtered.append(CalendarEvent(symbol=k, event_date=ev.event_date, source=ev.source, source_url=ev.source_url, confidence=ev.confidence * 0.8, result_type=ev.result_type))
                            break
                # else discard (likely garbage like URL)
            events = filtered
    except Exception:
        pass
    rows = [
        {
            "symbol": ev.symbol,
            "event_date": ev.event_date,
            "source": ev.source,
            "source_url": ev.source_url,
            "result_type": ev.result_type,
            "confidence": ev.confidence,
            "status": "pending",
        }
        for ev in events
    ]
    if rows:
        repo.upsert_earnings_calendar(rows)
        print(f"[Discovery] {target_date.isoformat()}: found {len(rows)} symbols via MCP: {', '.join(e.symbol for e in events[:20])}{'...' if len(events)>20 else ''}")
    else:
        print(f"[Discovery] {target_date.isoformat()}: no results found via MCP (checked NSE>BSE>MC)")
    return len(rows)
