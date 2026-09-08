from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def sign(secret: bytes, request_id: str, nonce: str, exit_ip: str, timestamp: int) -> str:
    value = f"{request_id}:{nonce}:{exit_ip}:{timestamp}".encode()
    return hmac.new(secret, value, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class EchoObservation:
    request_id: str
    nonce: str
    exit_ip: str
    observed_at: int
    region: str
    signature: str


class EchoVerifier:
    def __init__(self, secret: bytes) -> None:
        self.secret = secret

    def sign(self, request_id: str, nonce: str, exit_ip: str, timestamp: int) -> str:
        return sign(self.secret, request_id, nonce, exit_ip, timestamp)

    def verify(self, observation: EchoObservation, max_age_seconds: int = 30) -> bool:
        fresh = abs(int(time.time()) - observation.observed_at) <= max_age_seconds
        expected = self.sign(observation.request_id, observation.nonce, observation.exit_ip, observation.observed_at)
        return fresh and hmac.compare_digest(observation.signature, expected)


def make_handler(secret: bytes, region: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):  # noqa: A003
            return

        def do_GET(self):  # noqa: N802
            if self.path.rstrip("/") not in {"/echo", "/health"}:
                self.send_error(404)
                return
            if self.path.rstrip("/") == "/health":
                self._json(200, {"status": "ok", "region": region})
                return
            peer = self.client_address[0]
            request_id = self.headers.get("X-Request-Id") or ""
            nonce = self.headers.get("X-Nonce") or ""
            timestamp = int(self.headers.get("X-Timestamp") or int(time.time()))
            if self.headers.get("Content-Length"):
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                try:
                    body = json.loads(raw.decode() or "{}")
                    request_id = request_id or body.get("request_id", "")
                    nonce = nonce or body.get("nonce", "")
                    timestamp = int(body.get("timestamp", timestamp))
                except json.JSONDecodeError:
                    pass
            if not request_id or not nonce:
                self._json(400, {"error": "request_id and nonce required"})
                return
            payload = {
                "request_id": request_id,
                "nonce": nonce,
                "exit_ip": peer,
                "observed_at": int(time.time()),
                "timestamp": timestamp,
                "region": region,
                "signature": sign(secret, request_id, nonce, peer, timestamp),
            }
            self._json(200, payload)

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main() -> None:
    secret = os.environ.get("ECHO_SECRET", "dev-echo-secret").encode()
    region = os.environ.get("ECHO_REGION", "local")
    port = int(os.environ.get("ECHO_PORT", "8787"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(secret, region))
    server.serve_forever()


if __name__ == "__main__":
    main()
