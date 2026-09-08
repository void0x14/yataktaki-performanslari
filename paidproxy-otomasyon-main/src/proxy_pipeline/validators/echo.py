from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from uuid import uuid4

from proxy_pipeline.domain.time import utc_epoch_ms


@dataclass(frozen=True)
class EchoObservation:
    request_id: str
    nonce: str
    exit_ip: str
    observed_at: int
    region: str
    signature: str
    timestamp: int


class EchoClient:
    """Talks to a managed echo region through an already-established proxy tunnel."""

    def __init__(self, secret: bytes, region: str, host: str = "echo.invalid", path: str = "/echo") -> None:
        self.secret = secret
        self.region = region
        self.host = host
        self.path = path

    def sign(self, request_id: str, nonce: str, exit_ip: str, timestamp: int) -> str:
        value = f"{request_id}:{nonce}:{exit_ip}:{timestamp}".encode()
        return hmac.new(self.secret, value, hashlib.sha256).hexdigest()

    def request_bytes(self, request_id: str | None = None, nonce: str | None = None) -> tuple[bytes, str, str, int]:
        request_id = request_id or str(uuid4())
        nonce = nonce or str(uuid4())
        timestamp = utc_epoch_ms()
        body = json.dumps({"request_id": request_id, "nonce": nonce, "timestamp": timestamp}, sort_keys=True)
        payload = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}\r\n"
            f"X-Request-Id: {request_id}\r\n"
            f"X-Nonce: {nonce}\r\n"
            f"X-Timestamp: {timestamp}\r\n"
            "Connection: close\r\n"
            f"Content-Length: {len(body)}\r\n"
            "\r\n"
            f"{body}"
        )
        return payload.encode(), request_id, nonce, timestamp

    def parse_response(self, raw: bytes, request_id: str, nonce: str) -> EchoObservation:
        text = raw.decode("latin1", errors="replace")
        header, _, body = text.partition("\r\n\r\n")
        data = json.loads(body or "{}")
        if data.get("request_id") != request_id or data.get("nonce") != nonce:
            raise ValueError("echo nonce/request id mismatch")
        observation = EchoObservation(
            request_id=data["request_id"],
            nonce=data["nonce"],
            exit_ip=data["exit_ip"],
            observed_at=int(data.get("observed_at", data.get("timestamp", 0))),
            region=data.get("region", self.region),
            signature=data["signature"],
            timestamp=int(data.get("timestamp", 0)),
        )
        expected = self.sign(observation.request_id, observation.nonce, observation.exit_ip, observation.timestamp)
        if not hmac.compare_digest(observation.signature, expected):
            raise ValueError("echo signature mismatch")
        return observation
