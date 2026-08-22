from __future__ import annotations

import json
import os
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

        proxy_url = os.getenv("MF_PROXY_URL", "").strip()
        if proxy_url:
            self._session.proxies.update({"http": proxy_url, "https": proxy_url})

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

        last_status = 0
        last_body = ""

        for attempt in range(3):
            response = self._session.get(
                f"{self._base_url}{self.AUTOSUGGEST_PATH}", params=params, timeout=self._timeout
            )
            last_status = response.status_code

            if response.status_code in {403, 429, 503}:
                last_body = response.text[:120]
            else:
                payload = self._strip_jsonp(response.text)
                try:
                    entries: Iterable[Dict[str, Any]] = json.loads(payload)
                except json.JSONDecodeError:
                    # Empty or HTML body usually means bot-blocking; retry with a fresh session.
                    last_body = response.text[:120]
                    entries = None

                if entries is not None:
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

            if attempt < 2:
                self._reset_session()
                time.sleep((2 ** attempt) * 0.5 + random.random())
                continue

        raise RuntimeError(
            f"ticker lookup blocked after retries (status={last_status}, body={last_body!r})"
        )

    def fetch_overview_html(self, ticker: TickerInfo) -> str:
        return self._get_html_with_retry(ticker.link_src)

    def fetch_profit_loss_html(self, ticker: TickerInfo) -> str:
        return self._get_html_with_retry(self._financial_page_url(ticker, "profit-loss"))

    def fetch_ratios_html(self, ticker: TickerInfo, report: str = "consolidated") -> str:
        path_segment = self.REPORT_PATHS.get(report.lower())
        if path_segment is None:
            raise ValueError(f"Unsupported report type: {report}")

        ratios_url = f"{self._base_url}/financials/{ticker.stock_id}/{path_segment}/{ticker.stock_id}#{ticker.stock_id}"
        return self._get_html_with_retry(ratios_url)

    def close(self) -> None:
        self._session.close()

    # Helpers -----------------------------------------------------------------

    def _get_html_with_retry(self, url: str, *, attempts: int = 2) -> str:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = self._session.get(url, timeout=self._timeout)
                if response.status_code in {403, 429, 503}:
                    last_error = RuntimeError(f"blocked (status={response.status_code})")
                else:
                    response.raise_for_status()
                    return response.text
            except requests.RequestException as exc:
                last_error = exc
            if attempt < attempts - 1:
                self._reset_session()
                time.sleep(0.5 * (attempt + 1) + random.random())
        raise RuntimeError(f"GET {url} failed after {attempts} attempts: {last_error}")

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
