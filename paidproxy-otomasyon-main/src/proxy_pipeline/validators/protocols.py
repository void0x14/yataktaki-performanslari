from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import socket
import struct
import time


class ValidationResult(StrEnum):
    VALIDATED = "VALIDATED"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TIMEOUT = "TIMEOUT"
    UNREACHABLE = "UNREACHABLE"


@dataclass(frozen=True)
class Validation:
    protocol: str
    result: ValidationResult
    latency_ms: float | None
    reason: str
    echo_ref: str | None = None
    attempt: int = 1
    exit_ip: str | None = None


class Validator:
    protocol = ""

    def validate(
        self,
        host: str,
        port: int,
        timeout: float = 3.0,
        target: tuple[str, int] = ("example.invalid", 80),
        *,
        sock: socket.socket | None = None,
        echo=None,
    ) -> Validation:
        raise NotImplementedError


def _failure(protocol: str, started: float, result: ValidationResult, reason: str) -> Validation:
    return Validation(protocol, result, (time.monotonic() - started) * 1000, reason)


def _connect(host: str, port: int, timeout: float, sock: socket.socket | None) -> socket.socket:
    if sock is not None:
        return sock
    return socket.create_connection((host, port), timeout)


class HTTPConnectValidator(Validator):
    protocol = "http_connect"

    def validate(self, host, port, timeout=3.0, target=("example.invalid", 80), *, sock=None, echo=None):
        started = time.monotonic()
        conn = None
        try:
            conn = _connect(host, port, timeout, sock)
            conn.settimeout(timeout)
            request = f"CONNECT {target[0]}:{target[1]} HTTP/1.1\r\nHost: {target[0]}:{target[1]}\r\n\r\n"
            conn.sendall(request.encode())
            response = b""
            while b"\r\n\r\n" not in response and len(response) < 8192:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                response += chunk
            first = response.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
            if " 407 " in f" {first} " or first.endswith("407"):
                return _failure(self.protocol, started, ValidationResult.AUTH_REQUIRED, first)
            if " 200 " not in f" {first} " and not first.endswith("200 Connection established"):
                if first.startswith("HTTP/"):
                    return _failure(self.protocol, started, ValidationResult.PROTOCOL_MISMATCH, first)
                return _failure(self.protocol, started, ValidationResult.PROTOCOL_MISMATCH, first or "empty CONNECT response")
            echo_ref = None
            exit_ip = None
            if echo is not None:
                echo_ref, exit_ip = echo(conn)
            return Validation(
                self.protocol,
                ValidationResult.VALIDATED,
                (time.monotonic() - started) * 1000,
                first,
                echo_ref,
                exit_ip=exit_ip,
            )
        except TimeoutError:
            return _failure(self.protocol, started, ValidationResult.TIMEOUT, "connect timeout")
        except OSError as exc:
            return _failure(self.protocol, started, ValidationResult.UNREACHABLE, str(exc))
        finally:
            if conn is not None and sock is None:
                conn.close()


class SOCKS4Validator(Validator):
    protocol = "socks4"

    def validate(self, host, port, timeout=3.0, target=("example.invalid", 80), *, sock=None, echo=None):
        started = time.monotonic()
        conn = None
        try:
            conn = _connect(host, port, timeout, sock)
            conn.settimeout(timeout)
            try:
                packed = socket.inet_aton(target[0])
                payload = struct.pack("!BBH4s", 0x04, 0x01, target[1], packed) + b"proxy\x00"
            except OSError:
                payload = (
                    struct.pack("!BBH4s", 0x04, 0x01, target[1], b"\x00\x00\x00\x01")
                    + b"proxy\x00"
                    + target[0].encode()
                    + b"\x00"
                )
            conn.sendall(payload)
            reply = b""
            while len(reply) < 8:
                chunk = conn.recv(8 - len(reply))
                if not chunk:
                    break
                reply += chunk
            if len(reply) < 2 or reply[0] != 0x00:
                return _failure(self.protocol, started, ValidationResult.PROTOCOL_MISMATCH, f"socks4 reply={reply!r}")
            if reply[1] == 0x5B:
                return _failure(self.protocol, started, ValidationResult.UNREACHABLE, "socks4 request rejected")
            if reply[1] != 0x5A:
                return _failure(self.protocol, started, ValidationResult.PROTOCOL_MISMATCH, f"socks4 status={reply[1]}")
            echo_ref = None
            exit_ip = None
            if echo is not None:
                echo_ref, exit_ip = echo(conn)
            return Validation(
                self.protocol,
                ValidationResult.VALIDATED,
                (time.monotonic() - started) * 1000,
                "socks4 granted",
                echo_ref,
                exit_ip=exit_ip,
            )
        except TimeoutError:
            return _failure(self.protocol, started, ValidationResult.TIMEOUT, "connect timeout")
        except OSError as exc:
            return _failure(self.protocol, started, ValidationResult.UNREACHABLE, str(exc))
        finally:
            if conn is not None and sock is None:
                conn.close()


class SOCKS4AValidator(SOCKS4Validator):
    protocol = "socks4a"


class SOCKS5Validator(Validator):
    protocol = "socks5"

    def validate(self, host, port, timeout=3.0, target=("example.invalid", 80), *, sock=None, echo=None):
        started = time.monotonic()
        conn = None
        try:
            conn = _connect(host, port, timeout, sock)
            conn.settimeout(timeout)
            conn.sendall(b"\x05\x01\x00")
            method = conn.recv(2)
            if method == b"\x05\x02":
                return _failure(self.protocol, started, ValidationResult.AUTH_REQUIRED, "socks5 username/password required")
            if method != b"\x05\x00":
                return _failure(self.protocol, started, ValidationResult.PROTOCOL_MISMATCH, f"socks5 method={method!r}")
            try:
                addr = socket.inet_aton(target[0])
                request = b"\x05\x01\x00\x01" + addr + struct.pack("!H", target[1])
            except OSError:
                host_bytes = target[0].encode()
                request = b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack("!H", target[1])
            conn.sendall(request)
            reply = conn.recv(10)
            if not reply or reply[0] != 0x05:
                return _failure(self.protocol, started, ValidationResult.PROTOCOL_MISMATCH, f"socks5 reply={reply!r}")
            if reply[1] != 0x00:
                return _failure(self.protocol, started, ValidationResult.UNREACHABLE, f"socks5 status={reply[1]}")
            echo_ref = None
            exit_ip = None
            if echo is not None:
                echo_ref, exit_ip = echo(conn)
            return Validation(
                self.protocol,
                ValidationResult.VALIDATED,
                (time.monotonic() - started) * 1000,
                "socks5 succeeded",
                echo_ref,
                exit_ip=exit_ip,
            )
        except TimeoutError:
            return _failure(self.protocol, started, ValidationResult.TIMEOUT, "connect timeout")
        except OSError as exc:
            return _failure(self.protocol, started, ValidationResult.UNREACHABLE, str(exc))
        finally:
            if conn is not None and sock is None:
                conn.close()


class ValidatorPool:
    def __init__(self, validators: list[Validator] | None = None) -> None:
        self.validators = tuple(
            validators
            or [
                HTTPConnectValidator(),
                SOCKS5Validator(),
                SOCKS4Validator(),
                SOCKS4AValidator(),
            ]
        )

    def validate(self, host: str, port: int, protocols: tuple[str, ...], timeout: float = 3.0, **kwargs):
        selected = [v for name in protocols for v in self.validators if v.protocol == name]
        return [v.validate(host, port, timeout, **kwargs) for v in selected]
