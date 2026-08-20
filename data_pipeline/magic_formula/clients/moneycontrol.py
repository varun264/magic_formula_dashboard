from __future__ import annotations

import json
import random
import time
import warnings
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry

from ..models import TickerInfo


class MoneyControlClient:
    """HTTP client responsible for interacting with Moneycontrol endpoints."""

    AUTOSUGGEST_PATH = "/mccode/common/autosuggestion_solr.php/"
    REPORT_PATHS: Dict[str, str] = {
        "consolidated": "consolidated-ratiosVI",
        "standalone": "ratiosVI",
    }
    DEFAULT_HEADERS: Dict[str, str] = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Origin": "https://www.moneycontrol.com",
        "Pragma": "no-cache",
        "Referer": "https://www.moneycontrol.com/",
        "X-Requested-With": "XMLHttpRequest",
        "accept-version": "7.9.0",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
        ),
    }

    def __init__(
        self,
        base_url: str = "https://www.moneycontrol.com",
        *,
        session: Optional[requests.Session] = None,
        verify_ssl: bool = True,
        timeout: float = 15.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._verify_ssl = verify_ssl
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._session = session or self._build_session(max_retries=max_retries, backoff_factor=backoff_factor)

        if session is not None and max_retries > 0:
            retry = Retry(
                total=max_retries,
                backoff_factor=backoff_factor,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
            )
            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)

        if not verify_ssl:
            warnings.simplefilter("ignore", InsecureRequestWarning)
            self._session.verify = False
        else:
            self._session.verify = True

        self._session.headers.update(self.DEFAULT_HEADERS)

        # Prime cookies once so subsequent calls succeed.
        self._prime_session()

    def get_ticker(self, search_text: str) -> Optional[TickerInfo]:
        """Resolve a human-readable name into Moneycontrol ticker metadata."""
        params = {
            "classic": "true",
            "query": search_text,
            "type": "1",
            "format": "json",
            "callback": "suggest1",
        }

        for attempt in range(4):
            response = self._session.get(
                f"{self._base_url}{self.AUTOSUGGEST_PATH}", params=params, timeout=self._timeout
            )
            if response.status_code in {403, 429, 503}:
                if attempt < 3:
                    self._reset_session()
                    time.sleep((2 ** attempt) + random.random())
                    continue
                response.raise_for_status()

            response.raise_for_status()

            payload = self._strip_jsonp(response.text)
            entries: Iterable[Dict[str, Any]] = json.loads(payload)

            candidate = self._select_candidate(search_text, entries)
            if candidate is None:
                return None

            stock_id = candidate.get("sc_id", "").strip()
            link_src = candidate.get("link_src", "").strip()

            url_stock_id = self._extract_stock_id(link_src)
            if url_stock_id:
                stock_id = url_stock_id

            link_src = self._normalise_link(link_src)

            return TickerInfo(
                stock_id=stock_id,
                stock_name=candidate.get("stock_name", search_text),
                link_src=link_src,
                raw=dict(candidate),
            )

        raise RuntimeError("Failed to resolve ticker after retries")

    def fetch_overview_html(self, ticker: TickerInfo) -> str:
        response = self._session.get(ticker.link_src, timeout=self._timeout)
        response.raise_for_status()
        return response.text

    def fetch_profit_loss_html(self, ticker: TickerInfo) -> str:
        response = self._session.get(self._financial_page_url(ticker, "profit-loss"), timeout=self._timeout)
        response.raise_for_status()
        return response.text

    def fetch_ratios_html(self, ticker: TickerInfo, report: str = "consolidated") -> str:
        path_segment = self.REPORT_PATHS.get(report.lower())
        if path_segment is None:
            raise ValueError(f"Unsupported report type: {report}")

        ratios_url = f"{self._base_url}/financials/{ticker.stock_id}/{path_segment}/{ticker.stock_id}#{ticker.stock_id}"
        response = self._session.get(ratios_url, timeout=self._timeout)
        response.raise_for_status()
        return response.text

    def close(self) -> None:
        self._session.close()

    # Helpers -----------------------------------------------------------------

    def _build_session(self, *, max_retries: int, backoff_factor: float) -> requests.Session:
        session = requests.Session()
        if max_retries > 0:
            retry = Retry(
                total=max_retries,
                backoff_factor=backoff_factor,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET"],
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
        session.verify = self._verify_ssl
        session.headers.update(self.DEFAULT_HEADERS)
        return session

    def _financial_page_url(self, ticker: TickerInfo, section: str) -> str:
        link_parts = ticker.link_src.rstrip("/").split("/")
        slug_path = link_parts[-2] if len(link_parts) >= 2 else ticker.stock_id.lower()
        return f"{self._base_url}/markets/financials/{section}/{slug_path}-{ticker.stock_id}/#results"

    def _prime_session(self) -> None:
        try:
            self._session.get(f"{self._base_url}/", timeout=self._timeout)
        except requests.RequestException:
            # Moneycontrol occasionally rate-limits homepage priming; main requests still retry.
            return

    def _reset_session(self) -> None:
        self._session.close()
        self._session = self._build_session(max_retries=self._max_retries, backoff_factor=self._backoff_factor)
        self._prime_session()

    @staticmethod
    def _strip_jsonp(raw_text: str) -> str:
        prefix = "suggest1("
        if raw_text.startswith(prefix):
            return raw_text[len(prefix):-1]
        return raw_text

    @staticmethod
    def _select_candidate(search_text: str, entries: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        lowered = search_text.lower()
        for entry in entries:
            if entry.get("stock_name", "").lower() == lowered:
                return entry
        return next(iter(entries), None)

    @staticmethod
    def _extract_stock_id(link_src: str) -> Optional[str]:
        if not link_src:
            return None
        return link_src.rstrip("/").split("/")[-1] or None

    def _normalise_link(self, link_src: str) -> str:
        if not link_src:
            return self._base_url
        if link_src.startswith("http"):
            return link_src
        return urljoin(f"{self._base_url}/", link_src.lstrip("/"))
