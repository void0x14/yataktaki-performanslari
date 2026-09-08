"""Small JSON fetcher for discovery hosts; works with or without httpx."""
from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen


def get_json(url: str, *, timeout: float = 20.0, headers: dict[str, str] | None = None) -> Any:
    try:
        import httpx
    except ImportError:
        request = Request(url, headers=headers or {"Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    response = httpx.get(url, timeout=timeout, headers=headers or {"Accept": "application/json"})
    response.raise_for_status()
    return response.json()
