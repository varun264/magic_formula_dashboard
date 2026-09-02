from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Dict, List

from .base import CalendarEvent, CalendarSource


class CalendarResolver:
    """
    Priority-based dedup: NSE (3) > BSE (2) > MC (1).
    Extensible: add new CalendarSource via register().
    """

    def __init__(self, sources: List[CalendarSource]) -> None:
        # sort descending by priority
        self.sources = sorted(sources, key=lambda s: getattr(s, "priority", 0), reverse=True)

    def register(self, source: CalendarSource) -> None:
        self.sources.append(source)
        self.sources.sort(key=lambda s: getattr(s, "priority", 0), reverse=True)

    def discover(self, target_date: dt.date) -> List[CalendarEvent]:
        seen: Dict[str, CalendarEvent] = {}
        # Higher priority first: keep first occurrence, discard lower-priority dups
        for src in self.sources:
            try:
                events = src.fetch(target_date)
            except Exception:
                continue
            for ev in events:
                sym = ev.symbol.upper().strip()
                if not sym or len(sym) < 2 or len(sym) > 12:
                    continue
                # normalize
                sym = sym.upper()
                ev_norm = CalendarEvent(
                    symbol=sym,
                    event_date=ev.event_date,
                    source=src.source_name,
                    source_url=ev.source_url,
                    result_type=ev.result_type,
                    confidence=ev.confidence,
                )
                if sym not in seen:
                    seen[sym] = ev_norm
                else:
                    # keep higher priority (already inserted), but upgrade confidence if higher
                    existing = seen[sym]
                    if ev_norm.confidence > existing.confidence:
                        seen[sym] = CalendarEvent(
                            symbol=sym,
                            event_date=existing.event_date,
                            source=existing.source,
                            source_url=existing.source_url or ev_norm.source_url,
                            result_type=existing.result_type,
                            confidence=ev_norm.confidence,
                        )
        return sorted(seen.values(), key=lambda e: e.symbol)

    def discover_range(self, start: dt.date, end: dt.date) -> List[CalendarEvent]:
        all_events: Dict[tuple[str, str], CalendarEvent] = {}
        cur = start
        while cur <= end:
            for ev in self.discover(cur):
                key = (ev.symbol, ev.event_date)
                if key not in all_events:
                    all_events[key] = ev
            cur += dt.timedelta(days=1)
        return sorted(all_events.values(), key=lambda e: (e.event_date, e.symbol))
