from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Sequence, Set

import pandas as pd

from ..clients.moneycontrol import MoneyControlClient
from ..models import ScrapedStock
from ..parsers.overview import OverviewParser
from ..parsers.ratios import RatiosParser


ErrorHandler = Callable[[str, Exception], None]


class StockDataFetcher:
    """Coordinate data retrieval for one or more tickers."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], MoneyControlClient],
        overview_parser: OverviewParser,
        ratios_parser: RatiosParser,
        error_handler: Optional[ErrorHandler] = None,
    ) -> None:
        self._client_factory = client_factory
        self._overview_parser = overview_parser
        self._ratios_parser = ratios_parser
        self._error_handler = error_handler or self._default_error_handler
        self._thread_local = threading.local()
        self._clients: Set[MoneyControlClient] = set()
        self._clients_lock = threading.Lock()

    def fetch_many(self, symbols: Sequence[str], max_workers: int = 8) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()

        records: List[dict] = []

        try:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {executor.submit(self._fetch_single, symbol): symbol for symbol in symbols}

                for future in as_completed(future_map):
                    symbol = future_map[future]
                    try:
                        record = future.result()
                        if record is not None:
                            records.append(record)
                    except Exception as exc:  # safety net for unexpected failures
                        self._error_handler(symbol, exc)
        finally:
            self._cleanup_clients()

        return pd.DataFrame(records)

    # Internal ----------------------------------------------------------------

    def _fetch_single(self, symbol: str) -> Optional[dict]:
        client = self._get_client()

        ticker = client.get_ticker(symbol)
        if ticker is None:
            return None

        overview_html = client.fetch_overview_html(ticker)
        ratios_html = client.fetch_ratios_html(ticker)

        overview = self._overview_parser.parse(overview_html)
        ratios = self._ratios_parser.parse(ratios_html)

        stock = ScrapedStock(ticker=ticker, overview=overview, ratios=ratios)
        return stock.to_record()

    def _get_client(self) -> MoneyControlClient:
        client = getattr(self._thread_local, "client", None)
        if client is not None:
            return client

        client = self._client_factory()
        setattr(self._thread_local, "client", client)
        with self._clients_lock:
            self._clients.add(client)
        return client

    def _cleanup_clients(self) -> None:
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()

        for client in clients:
            client.close()

    @staticmethod
    def _default_error_handler(symbol: str, error: Exception) -> None:
        print(f"[Error] Failed to process {symbol}: {error}")
