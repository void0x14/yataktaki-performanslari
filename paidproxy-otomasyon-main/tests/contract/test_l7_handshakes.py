from __future__ import annotations

import socket
import struct
import threading

from proxy_pipeline.validators.protocols import (
    HTTPConnectValidator,
    SOCKS4Validator,
    SOCKS5Validator,
    ValidationResult,
    ValidatorPool,
)


class FakeSocket:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)
        self.sent = b""
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, data):
        self.sent += data

    def recv(self, n):
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        return chunk[:n]

    def close(self):
        return None


def test_http_connect_200_is_validated():
    sock = FakeSocket([b"HTTP/1.1 200 Connection established\r\n\r\n"])
    result = HTTPConnectValidator().validate("198.51.100.1", 3128, sock=sock)
    assert result.result is ValidationResult.VALIDATED
    assert b"CONNECT" in sock.sent


def test_http_connect_407_is_auth_required():
    sock = FakeSocket([b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"])
    result = HTTPConnectValidator().validate("198.51.100.1", 3128, sock=sock)
    assert result.result is ValidationResult.AUTH_REQUIRED


def test_socks5_noauth_success():
    sock = FakeSocket([b"\x05\x00", b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00"])
    result = SOCKS5Validator().validate("198.51.100.1", 1080, sock=sock, target=("1.2.3.4", 80))
    assert result.result is ValidationResult.VALIDATED
    assert sock.sent.startswith(b"\x05\x01\x00")


def test_socks5_auth_required():
    sock = FakeSocket([b"\x05\x02"])
    result = SOCKS5Validator().validate("198.51.100.1", 1080, sock=sock)
    assert result.result is ValidationResult.AUTH_REQUIRED


def test_socks4_granted():
    sock = FakeSocket([b"\x00\x5a\x00\x00\x00\x00\x00\x00"])
    result = SOCKS4Validator().validate("198.51.100.1", 1080, sock=sock, target=("1.2.3.4", 80))
    assert result.result is ValidationResult.VALIDATED


def test_validator_pool_honors_caller_protocol_order():
    pool = ValidatorPool()
    selected = [v.protocol for name in ("socks5", "http_connect") for v in pool.validators if v.protocol == name]
    assert selected == ["socks5", "http_connect"]
