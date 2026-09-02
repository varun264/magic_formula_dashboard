from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Protocol


@dataclass(frozen=True)
class CalendarEvent:
    symbol: str
    event_date: str  # YYYY-MM-DD
    source: str  # NSE|BSE|MC|MANUAL
    source_url: str | None = None
    result_type: str = "quarterly"
    confidence: float = 1.0


class CalendarSource(Protocol):
    source_name: str
    priority: int

    def fetch(self, target_date: dt.date) -> List[CalendarEvent]: ...
