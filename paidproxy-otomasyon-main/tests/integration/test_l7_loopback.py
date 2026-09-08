from __future__ import annotations

import socket
import threading

from proxy_pipeline.validators.protocols import HTTPConnectValidator, ValidationResult


def _serve_once(server: socket.socket, payload: bytes) -> None:
    conn, _ = server.accept()
    with conn:
        conn.recv(4096)
        conn.sendall(payload)


def test_http_connect_against_loopback_fixture():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    thread = threading.Thread(
        target=_serve_once,
        args=(server, b"HTTP/1.1 200 Connection established\r\n\r\n"),
        daemon=True,
    )
    thread.start()
    result = HTTPConnectValidator().validate("127.0.0.1", port, timeout=2.0)
    thread.join(2)
    server.close()
    assert result.result is ValidationResult.VALIDATED
