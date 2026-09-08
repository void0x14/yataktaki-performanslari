from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from proxy_pipeline.sources.catalog import SourceMetadata


@dataclass
class JsonSourceConnector:
    metadata: SourceMetadata
    endpoint: str
    timeout: float = 10.0
    allowed_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("source endpoint must use HTTPS")
        if self.allowed_hosts and parsed.hostname not in self.allowed_hosts:
            raise ValueError("source host is not on the connector allowlist")

    def fetch(self, query: dict) -> list[dict]:
        request = Request(
            self.endpoint,
            data=json.dumps(query).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError("source response must be an object list")
        return payload

    def health_check(self) -> bool:
        return self.metadata.health != "unhealthy"
