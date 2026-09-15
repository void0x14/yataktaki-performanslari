"""Small JSON fetcher for discovery hosts; works with or without httpx."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


def get_json(url: str, *, timeout: float = 20.0, headers: dict[str, str] | None = None) -> Any:
    try:
        import httpx
    except ImportError:
        opener = build_opener(HTTPRedirectHandler())
        request = Request(url, headers=headers or {"Accept": "application/json"})
        with opener.open(request, timeout=timeout) as response:
            final = response.geturl()
            if urlparse(final).scheme != "https":
                raise RuntimeError(f"RDAP güvensiz redirect reddedildi ({final})")
            return json.loads(response.read())
    response = httpx.get(url, timeout=timeout, headers=headers or {"Accept": "application/json"},
                          follow_redirects=True)
    response.raise_for_status()
    return response.json()
