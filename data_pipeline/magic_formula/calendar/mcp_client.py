from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import List, Optional

import requests


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str


class MCPSearchClient:
    """
    Pluggable web-search via free MCP servers.

    Priority chain (keyless):
      1. Parallel Search MCP https://search.parallel.ai/mcp
      2. Firecrawl MCP https://mcp.firecrawl.dev/v2/mcp
      3. Direct HTTP fallback (NSE/BSE calendar pages) — always available.

    In CI, if MCP env not configured, falls back to direct HTTP without failing.
    Extensible: add new server by adding entry to MCP_SERVERS.
    """

    MCP_SERVERS = [
        {
            "name": "parallel",
            "url": os.getenv("MCP_PARALLEL_URL", "https://search.parallel.ai/mcp"),
            "kind": "parallel",
        },
        {
            "name": "firecrawl",
            "url": os.getenv("MCP_FIRECRAWL_URL", "https://mcp.firecrawl.dev/v2/mcp"),
            "kind": "firecrawl",
        },
    ]

    def __init__(self, timeout: float = 12.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/127.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
            }
        )

    def search(self, query: str, limit: int = 5) -> List[SearchResult]:
        for server in self.MCP_SERVERS:
            try:
                results = self._search_via_mcp(server, query, limit)
                if results:
                    return results
            except Exception:
                continue
        return []

    def fetch(self, url: str) -> Optional[str]:
        for server in self.MCP_SERVERS:
            try:
                text = self._fetch_via_mcp(server, url)
                if text:
                    return text
            except Exception:
                continue
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.ok:
                return resp.text[:20000]
        except Exception:
            return None
        return None

    def _parse_mcp_response(self, text: str) -> dict:
        import json

        try:
            return json.loads(text)
        except Exception:
            pass
        for line in text.splitlines():
            if line.startswith("data:"):
                j = line[len("data:") :].strip()
                if not j:
                    continue
                try:
                    return json.loads(j)
                except Exception:
                    continue
        return {}

    def _search_via_mcp(self, server: dict, query: str, limit: int) -> List[SearchResult]:
        import json
        import uuid

        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if server["kind"] == "parallel":
            sid = getattr(self, "_session_id", None)
            if not sid:
                sid = str(uuid.uuid4())
                self._session_id = sid  # type: ignore[attr-defined]
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "web_search",
                    "arguments": {
                        "objective": query,
                        "search_queries": [query[:60], query[:40] + " results calendar", "NSE BSE earnings " + query[:20]],
                        "session_id": sid,
                        "model_name": "muse-spark-1.2",
                    },
                },
            }
            resp = self.session.post(server["url"], json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = self._parse_mcp_response(resp.text)
            results: List[SearchResult] = []
            try:
                content = data.get("result", {}).get("content", [])
                if content and isinstance(content[0].get("text"), str):
                    inner = json.loads(content[0]["text"])
                    for r in inner.get("results", [])[:limit]:
                        url = r.get("url", "")
                        title = r.get("title", "") or ""
                        excerpts = r.get("excerpts") or []
                        snippet = " ".join(excerpts)[:800] if excerpts else ""
                        results.append(SearchResult(url=url, title=title, snippet=snippet))
                    return results
            except Exception:
                pass
            # fallback generic extract
            def _extract(obj) -> None:
                if isinstance(obj, dict):
                    if "url" in obj and "title" in obj:
                        results.append(SearchResult(url=obj["url"], title=obj.get("title", ""), snippet=obj.get("snippet", "")[:500]))
                    for v in obj.values():
                        if isinstance(v, (dict, list)):
                            _extract(v)
                elif isinstance(obj, list):
                    for it in obj:
                        _extract(it)

            _extract(data)
            return results[:limit]

        if server["kind"] == "firecrawl":
            payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "firecrawl_search", "arguments": {"query": query, "limit": limit}},
            }
            resp = self.session.post(server["url"], json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = self._parse_mcp_response(resp.text)
            results: List[SearchResult] = []
            try:
                # Firecrawl result shape: result.content[0].text is JSON with results
                content = data.get("result", {}).get("content", []) if isinstance(data.get("result"), dict) else []
                if content:
                    txt = content[0].get("text", "")
                    if txt:
                        inner = json.loads(txt) if txt.strip().startswith("{") else {}
                        # firecrawl_search returns {"success": true, "data": [{"url":..., "title":...}]}
                        for item in (inner.get("data") or inner.get("results") or [])[:limit]:
                            if isinstance(item, dict) and item.get("url"):
                                results.append(SearchResult(url=item["url"], title=item.get("title", "")[:120], snippet=item.get("description", "")[:500] or item.get("markdown", "")[:500]))
                        if results:
                            return results
            except Exception:
                pass
            # generic fallback
            def _extract2(o) -> None:
                if isinstance(o, dict):
                    if "url" in o and isinstance(o["url"], str) and o["url"].startswith("http"):
                        results.append(SearchResult(url=o["url"], title=o.get("title", "")[:120], snippet=o.get("description", "")[:500]))
                    for v in o.values():
                        if isinstance(v, (dict, list)):
                            _extract2(v)
                elif isinstance(o, list):
                    for it in o:
                        _extract2(it)

            _extract2(data)
            return results[:limit]

        # generic fallback for other kinds
        payload = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"query": query, "count": limit}},
        }
        resp = self.session.post(server["url"], json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = self._parse_mcp_response(resp.text)
        results: List[SearchResult] = []
        def _extract3(o) -> None:
            if isinstance(o, dict):
                if "url" in o and "title" in o:
                    results.append(SearchResult(url=o["url"], title=o.get("title", ""), snippet=o.get("snippet", "")[:500]))
                for v in o.values():
                    if isinstance(v, (dict, list)):
                        _extract3(v)
            elif isinstance(o, list):
                for it in o:
                    _extract3(it)

        _extract3(data)
        return results[:limit]

    def _fetch_via_mcp(self, server: dict, url: str) -> Optional[str]:
        import json
        import uuid

        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if server["kind"] == "parallel":
            sid = getattr(self, "_session_id", None)
            if not sid:
                sid = str(uuid.uuid4())
                self._session_id = sid  # type: ignore[attr-defined]
            payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "web_fetch",
                    "arguments": {"urls": [url], "objective": f"Extract forthcoming results calendar for {url}", "session_id": sid, "model_name": "muse-spark-1.2"},
                },
            }
            resp = self.session.post(server["url"], json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = self._parse_mcp_response(resp.text)
            try:
                content = data.get("result", {}).get("content", [])
                if content:
                    txt = content[0].get("text", "")
                    if txt and len(txt) > 200:
                        return txt[:20000]
                    # parallel sometimes returns JSON with excerpts
                    inner = json.loads(txt) if txt.strip().startswith("{") else {}
                    if isinstance(inner, dict) and inner.get("results"):
                        # combine excerpts
                        parts = []
                        for r in inner["results"]:
                            if r.get("url") == url:
                                parts.extend(r.get("excerpts", []))
                        if parts:
                            return "\n".join(parts)[:20000]
            except Exception:
                pass
            # fallback generic
            def find_text(o):
                if isinstance(o, dict):
                    if "text" in o and isinstance(o["text"], str) and len(o["text"]) > 200:
                        return o["text"]
                    for v in o.values():
                        t = find_text(v)
                        if t:
                            return t
                elif isinstance(o, list):
                    for it in o:
                        t = find_text(it)
                        if t:
                            return t
                return None

            t = find_text(data)
            return t[:20000] if t else None

        if server["kind"] == "firecrawl":
            payload = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "firecrawl_scrape", "arguments": {"url": url, "formats": ["markdown"]}},
            }
            resp = self.session.post(server["url"], json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = self._parse_mcp_response(resp.text)
            try:
                content = data.get("result", {}).get("content", []) if isinstance(data.get("result"), dict) else []
                if content:
                    txt = content[0].get("text", "")
                    if txt:
                        inner = json.loads(txt) if txt.strip().startswith("{") else {}
                        # firecrawl_scrape returns {"markdown": "...", "metadata":...}
                        if isinstance(inner, dict) and inner.get("markdown"):
                            return inner["markdown"][:20000]
                        if isinstance(inner, dict) and inner.get("data", {}).get("markdown"):
                            return inner["data"]["markdown"][:20000]
                        return txt[:20000]
            except Exception:
                pass
            def find_text2(o):
                if isinstance(o, dict):
                    if "markdown" in o and isinstance(o["markdown"], str) and len(o["markdown"]) > 200:
                        return o["markdown"]
                    if "text" in o and isinstance(o["text"], str) and len(o["text"]) > 200:
                        return o["text"]
                    for v in o.values():
                        t = find_text2(v)
                        if t:
                            return t
                elif isinstance(o, list):
                    for it in o:
                        t = find_text2(it)
                        if t:
                            return t
                return None

            t = find_text2(data)
            return t[:20000] if t else None

        # generic fallback
        try:
            payload = {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "fetch", "arguments": {"url": url}}}
            resp = self.session.post(server["url"], json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = self._parse_mcp_response(resp.text)
            def find_text3(o):
                if isinstance(o, dict):
                    if "text" in o and isinstance(o["text"], str) and len(o["text"]) > 200:
                        return o["text"]
                    for v in o.values():
                        t = find_text3(v)
                        if t:
                            return t
                elif isinstance(o, list):
                    for it in o:
                        t = find_text3(it)
                        if t:
                            return t
                return None

            t = find_text3(data)
            return t[:20000] if t else None
        except Exception:
            return None
