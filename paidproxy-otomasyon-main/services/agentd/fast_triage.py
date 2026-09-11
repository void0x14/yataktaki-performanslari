"""Fast Asynchronous Port Triage and Neutral Egress Validation Engine.

Pure Python standard library (asyncio + socket + ssl), zero external dependencies.
Capable of concurrently probing 1,000+ open ports within seconds.

Key Capabilities:
1. Two-step triage: Connect verification followed by protocol handshakes (HTTP CONNECT, SOCKS5).
2. Neutral egress verification: Tests against non-bannable endpoints (e.g. 1.1.1.1/cdn-cgi/trace, api.ipify.org)
   to prove actual internet egress and determine external exit IP.
3. Concurrency control via asyncio.Semaphore to prevent local FD exhaustion.
4. Adheres strictly to measured VDS physics (docs/masscan-hiz-ve-timeout.md):
   timeout >= 1.0s (default 1.5s), 2 retries per port.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import ipaddress
import json
import logging
from pathlib import Path
import re
import socket
import ssl
import time
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger("agentd.fast_triage")

# Default neutral egress endpoints that never rate-limit or ban scanner IPs
DEFAULT_EGRESS_ENDPOINTS = [
    {"url": "http://1.1.1.1/cdn-cgi/trace", "host": "1.1.1.1", "port": 80, "path": "/cdn-cgi/trace", "ssl": False},
    {"url": "http://api.ipify.org/", "host": "api.ipify.org", "port": 80, "path": "/", "ssl": False},
]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FastTriageEngine:
    def __init__(
        self,
        concurrency: int = 500,
        connect_timeout: float = 1.5,
        retries: int = 2,
    ) -> None:
        self.concurrency = max(1, min(concurrency, 2000))
        self.connect_timeout = max(1.0, float(connect_timeout))
        self.retries = max(1, int(retries))
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

    async def probe_http_connect(
        self,
        host: str,
        port: int,
        egress_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Probe a single port with HTTP CONNECT and verify outbound egress."""
        target = egress_target or DEFAULT_EGRESS_ENDPOINTS[0]
        target_host = str(target["host"])
        target_port = int(target["port"])
        target_path = str(target.get("path", "/"))
        is_ssl = bool(target.get("ssl", False))

        started = time.monotonic()
        for attempt in range(1, self.retries + 1):
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=self.connect_timeout,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                if attempt == self.retries:
                    return {
                        "protocol": "http_connect",
                        "stage": "connect",
                        "error": str(exc),
                        "proxy_detected": False,
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }
                await asyncio.sleep(0.1)
                continue

            try:
                connect_req = (
                    f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
                    f"Host: {target_host}:{target_port}\r\n"
                    "Proxy-Connection: Keep-Alive\r\n"
                    "User-Agent: paidproxy-fast-triage/1.0\r\n\r\n"
                ).encode("utf-8")
                writer.write(connect_req)
                await asyncio.wait_for(writer.drain(), timeout=self.connect_timeout)

                header_data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=self.connect_timeout)
                first_line = header_data.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
                match = re.search(r"HTTP/\d(?:\.\d)?\s+(\d+)", first_line)
                status_code = int(match.group(1)) if match else None

                if status_code == 407:
                    return {
                        "protocol": "http_connect",
                        "stage": "connect",
                        "response_line": first_line,
                        "http_status": 407,
                        "proxy_detected": True,
                        "auth_required": True,
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }

                if status_code != 200:
                    return {
                        "protocol": "http_connect",
                        "stage": "connect",
                        "response_line": first_line,
                        "http_status": status_code,
                        "proxy_detected": False,
                        "auth_required": False,
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }

                # Status is 200 OK -> Tunnel established. Now test outbound egress request
                get_req = (
                    f"GET {target_path} HTTP/1.1\r\n"
                    f"Host: {target_host}\r\n"
                    "Connection: close\r\n"
                    "User-Agent: paidproxy-fast-triage/1.0\r\n\r\n"
                ).encode("utf-8")
                writer.write(get_req)
                await asyncio.wait_for(writer.drain(), timeout=self.connect_timeout)

                body_data = await asyncio.wait_for(reader.read(4096), timeout=self.connect_timeout)
                body_str = body_data.decode("latin1", errors="replace")

                exit_ip = None
                egress_confirmed = False

                # Extract IP from 1.1.1.1/cdn-cgi/trace
                ip_match = re.search(r"\bip=([0-9a-fA-F.:]+)", body_str)
                if ip_match:
                    exit_ip = ip_match.group(1)
                    egress_confirmed = True
                elif "origin" in body_str.lower() or "httpbin" in body_str.lower():
                    egress_confirmed = True

                return {
                    "protocol": "http_connect",
                    "stage": "egress",
                    "response_line": first_line,
                    "http_status": 200,
                    "proxy_detected": True,
                    "auth_required": False,
                    "egress_confirmed": egress_confirmed,
                    "exit_ip": exit_ip,
                    "body_preview": body_str[:200],
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                }

            except (OSError, asyncio.TimeoutError) as exc:
                return {
                    "protocol": "http_connect",
                    "stage": "handshake",
                    "error": str(exc),
                    "proxy_detected": False,
                    "egress_confirmed": False,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                }
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        return {"protocol": "http_connect", "stage": "timeout", "egress_confirmed": False}

    async def probe_socks5(
        self,
        host: str,
        port: int,
        egress_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Probe a single port with SOCKS5 handshake and verify outbound egress."""
        target = egress_target or DEFAULT_EGRESS_ENDPOINTS[0]
        target_host = str(target["host"])
        target_port = int(target["port"])
        target_path = str(target.get("path", "/"))

        started = time.monotonic()
        for attempt in range(1, self.retries + 1):
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=self.connect_timeout,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                if attempt == self.retries:
                    return {
                        "protocol": "socks5",
                        "stage": "connect",
                        "error": str(exc),
                        "proxy_detected": False,
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }
                await asyncio.sleep(0.1)
                continue

            try:
                # SOCKS5 Greeting: 1 method, No Authentication (0x00)
                writer.write(b"\x05\x01\x00")
                await asyncio.wait_for(writer.drain(), timeout=self.connect_timeout)

                method_reply = await asyncio.wait_for(reader.readexactly(2), timeout=self.connect_timeout)
                if method_reply[0] != 0x05:
                    return {
                        "protocol": "socks5",
                        "stage": "greeting",
                        "proxy_detected": False,
                        "egress_confirmed": False,
                        "response": repr(method_reply),
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }

                if method_reply[1] == 0xFF:
                    return {
                        "protocol": "socks5",
                        "stage": "greeting",
                        "proxy_detected": True,
                        "auth_required": True,
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }

                if method_reply[1] != 0x00:
                    return {
                        "protocol": "socks5",
                        "stage": "greeting",
                        "proxy_detected": True,
                        "auth_required": True,
                        "method": method_reply[1],
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }

                # SOCKS5 Connect Request to target IPv4 or domain
                try:
                    target_ip = socket.gethostbyname(target_host)
                    req = b"\x05\x01\x00\x01" + socket.inet_aton(target_ip) + target_port.to_bytes(2, "big")
                except OSError:
                    domain_bytes = target_host.encode("ascii")
                    req = b"\x05\x01\x00\x03" + bytes([len(domain_bytes)]) + domain_bytes + target_port.to_bytes(2, "big")

                writer.write(req)
                await asyncio.wait_for(writer.drain(), timeout=self.connect_timeout)

                connect_reply = await asyncio.wait_for(reader.read(10), timeout=self.connect_timeout)
                if len(connect_reply) < 4 or connect_reply[1] != 0x00:
                    rep_code = connect_reply[1] if len(connect_reply) >= 2 else None
                    return {
                        "protocol": "socks5",
                        "stage": "connect",
                        "proxy_detected": True,
                        "rep_code": rep_code,
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }

                # Egress HTTP request over SOCKS5 tunnel
                get_req = (
                    f"GET {target_path} HTTP/1.1\r\n"
                    f"Host: {target_host}\r\n"
                    "Connection: close\r\n"
                    "User-Agent: paidproxy-fast-triage/1.0\r\n\r\n"
                ).encode("utf-8")
                writer.write(get_req)
                await asyncio.wait_for(writer.drain(), timeout=self.connect_timeout)

                body_data = await asyncio.wait_for(reader.read(4096), timeout=self.connect_timeout)
                body_str = body_data.decode("latin1", errors="replace")

                exit_ip = None
                egress_confirmed = False
                ip_match = re.search(r"\bip=([0-9a-fA-F.:]+)", body_str)
                if ip_match:
                    exit_ip = ip_match.group(1)
                    egress_confirmed = True

                return {
                    "protocol": "socks5",
                    "stage": "egress",
                    "proxy_detected": True,
                    "auth_required": False,
                    "egress_confirmed": egress_confirmed,
                    "exit_ip": exit_ip,
                    "body_preview": body_str[:200],
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                }

            except (OSError, asyncio.TimeoutError) as exc:
                return {
                    "protocol": "socks5",
                    "stage": "handshake",
                    "error": str(exc),
                    "proxy_detected": False,
                    "egress_confirmed": False,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                }
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        return {"protocol": "socks5", "stage": "timeout", "egress_confirmed": False}

    async def probe_endpoint(
        self,
        host: str,
        port: int,
        protocols: list[str] | None = None,
        egress_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Probe an endpoint with all requested protocols."""
        target_protocols = protocols or ["http_connect", "socks5"]
        results = []
        for proto in target_protocols:
            if proto == "http_connect":
                res = await self.probe_http_connect(host, port, egress_target)
            elif proto == "socks5":
                res = await self.probe_socks5(host, port, egress_target)
            else:
                continue
            results.append(res)

        confirmed = [r for r in results if r.get("egress_confirmed")]
        detected = [r for r in results if r.get("proxy_detected")]
        return {
            "host": host,
            "port": port,
            "results": results,
            "egress_confirmed": len(confirmed) > 0,
            "proxy_detected": len(detected) > 0,
            "verified_protocols": [r["protocol"] for r in confirmed],
            "exit_ip": confirmed[0].get("exit_ip") if confirmed else None,
            "observed_at": _utc_iso(),
        }

    async def triage_cluster(
        self,
        host_port_pairs: list[tuple[str, int]],
        protocols: list[str] | None = None,
        egress_target: dict[str, Any] | None = None,
        check_cancel: Callable[[], bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Concurrently triage hundreds/thousands of host-port candidates."""
        sem = asyncio.Semaphore(self.concurrency)

        async def _worker(h: str, p: int) -> dict[str, Any]:
            if check_cancel and check_cancel():
                return {"host": h, "port": p, "results": [], "canceled": True}
            async with sem:
                if check_cancel and check_cancel():
                    return {"host": h, "port": p, "results": [], "canceled": True}
                return await self.probe_endpoint(h, p, protocols, egress_target)

        tasks = [_worker(h, p) for h, p in host_port_pairs]
        return await asyncio.gather(*tasks)


def run_fast_triage(
    host_port_pairs: list[tuple[str, int]],
    concurrency: int = 500,
    connect_timeout: float = 1.5,
    retries: int = 2,
    output_path: Path | str | None = None,
    check_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Synchronous entry point for running fast triage and persisting live proxies."""
    engine = FastTriageEngine(concurrency=concurrency, connect_timeout=connect_timeout, retries=retries)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(
            engine.triage_cluster(host_port_pairs, check_cancel=check_cancel)
        )
    finally:
        loop.close()

    live_proxies = [item for item in results if item.get("egress_confirmed")]

    if output_path and live_proxies:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "a", encoding="utf-8") as f:
            for item in live_proxies:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    return {
        "scanned_count": len(host_port_pairs),
        "live_count": len(live_proxies),
        "live_proxies": live_proxies,
        "all_results": results,
    }
