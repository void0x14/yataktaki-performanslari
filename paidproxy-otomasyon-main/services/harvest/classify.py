"""5-protokol L7 doğrulama + egress sınıflandırma (stdlib-only, asyncio).

Protokoller: HTTP-FWD, HTTP-CON, SOCKS4, SOCKS4a, SOCKS5.
Sınıflar (Proxymaker doktrini):
  - v6_forward : dinleyici v4, çıkış IPv6 (piyasadaki altın kategori)
  - rotate     : ardışık 3 istekte egress IP değişiyor
  - v4_forward : statik v4 çıkışlı forward proxy
  - http_connect / socks5 / socks4 / socks4a : protokol bazlı kovalar

Egress kanıtı: nötr uç (http://ifconfig.me / http://api.ipify.org) üzerinden
tünel içi GET; yanıt gövdesinden çıkış IP'si okunur.
"""
from __future__ import annotations

import asyncio
import ipaddress
import struct
from dataclasses import dataclass, field

EGRESS_HOSTS = ("ifconfig.me", "api.ipify.org", "icanhazip.com")
EGRESS_PATH = "/ip"


@dataclass
class Verdict:
    ip: str
    port: int
    protocol: str | None = None       # http_fwd|http_con|socks4|socks4a|socks5
    egress_ip: str | None = None
    bucket: str | None = None          # v6_forward|rotate|v4_forward|<protocol>
    latency_ms: float = 0.0
    alive: bool = False


async def _read_until(reader: asyncio.StreamReader, marker: bytes,
                      limit: int = 8192, timeout: float = 1.5) -> bytes:
    buf = b""
    try:
        while marker not in buf and len(buf) < limit:
            chunk = await asyncio.wait_for(reader.read(1024), timeout)
            if not chunk:
                break
            buf += chunk
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    return buf
    return buf


async def _read_body(reader: asyncio.StreamReader,
                     limit: int = 4096, timeout: float = 1.5) -> bytes:
    """Gövdeyi bağlantı kapanana/limit/timeout'a kadar oku.

    _read_until(reader, b"") ÇAĞRISI YASAK: boş marker her buffer'da 'var'
    sayılır, döngü hiç çalışmaz, gövde hep boş döner (29k açık portun
    sıfır doğrulanmasının kök nedeni)."""
    buf = b""
    try:
        while len(buf) < limit:
            chunk = await asyncio.wait_for(reader.read(1024), timeout)
            if not chunk:
                break
            buf += chunk
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    return buf


async def _http_fwd_probe(ip: str, port: int, host: str, timeout: float) -> tuple[bool, str | None]:
    """Düz forward GET — proxy hedef sayfayı kendi çıkışıyla döner."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None
    try:
        req = (f"GET http://{host}{EGRESS_PATH} HTTP/1.1\r\n"
               f"Host: {host}\r\nConnection: close\r\n\r\n")
        writer.write(req.encode())
        await asyncio.wait_for(writer.drain(), timeout)
        raw = await _read_until(reader, b"\r\n\r\n", timeout=timeout)
        if not raw.startswith(b"HTTP/"):
            return False, None
        head, _, body = raw.partition(b"\r\n\r\n")
        status = head.split(b" ", 2)[1] if b" " in head else b""
        if status.startswith(b"4") or status.startswith(b"5"):
            return False, None
        if len(body) < 7:  # IP henüz gelmediyse kalanını oku
            body += await _read_body(reader, limit=4096 - len(body), timeout=timeout)
        text = body.decode("latin1", errors="replace").strip()
        candidate = text.split()[-1] if text else ""
        try:
            ipaddress.ip_address(candidate)
            return True, candidate
        except ValueError:
            return False, None  # 200 ama gövde IP değil — Webmin/panel, proxy DEĞİL
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _connect_tunnel(ip: str, port: int, host: str, timeout: float,
                          proto: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """CONNECT veya SOCKS el sıkışmasıyla host:80 tüneli aç."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return None
    try:
        if proto == "http_con":
            writer.write(f"CONNECT {host}:80 HTTP/1.1\r\nHost: {host}:80\r\n\r\n".encode())
            await asyncio.wait_for(writer.drain(), timeout)
            head = await _read_until(reader, b"\r\n\r\n", timeout=timeout)
            first = head.split(b"\r\n", 1)[0]
            if b" 200" not in b" " + first + b" " and not first.endswith(b"200"):
                raise ValueError("connect rejected")
        elif proto == "socks5":
            writer.write(b"\x05\x01\x00")
            await asyncio.wait_for(writer.drain(), timeout)
            method = await asyncio.wait_for(reader.readexactly(2), timeout)
            if method != b"\x05\x00":
                raise ValueError("socks5 auth/method")
            hb = host.encode()
            writer.write(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack("!H", 80))
            await asyncio.wait_for(writer.drain(), timeout)
            reply = await asyncio.wait_for(reader.readexactly(10), timeout)
            if reply[1] != 0x00:
                raise ValueError("socks5 connect fail")
        elif proto in ("socks4", "socks4a"):
            if proto == "socks4":
                try:
                    packed = ipaddress.IPv4Address(host).packed
                    payload = struct.pack("!BBH4s", 4, 1, 80, packed) + b"p\x00"
                except ipaddress.AddressValueError:
                    raise ValueError("socks4 needs ip")
            else:
                payload = (struct.pack("!BBH4s", 4, 1, 80, b"\x00\x00\x00\x01")
                           + b"p\x00" + host.encode() + b"\x00")
            writer.write(payload)
            await asyncio.wait_for(writer.drain(), timeout)
            reply = await asyncio.wait_for(reader.readexactly(8), timeout)
            if reply[1] != 0x5A:
                raise ValueError("socks4 rejected")
        return reader, writer
    except (asyncio.TimeoutError, ConnectionError, OSError,
            ValueError, asyncio.IncompleteReadError):
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return None


async def _egress_via_tunnel(reader, writer, host: str, timeout: float) -> str | None:
    try:
        writer.write(f"GET {EGRESS_PATH} HTTP/1.1\r\nHost: {host}\r\n"
                     f"Connection: close\r\n\r\n".encode())
        await asyncio.wait_for(writer.drain(), timeout)
        raw = await _read_until(reader, b"\r\n\r\n", timeout=timeout)
        if not raw.startswith(b"HTTP/"):
            return None
        _, _, body = raw.partition(b"\r\n\r\n")
        if len(body) < 7:
            body += await _read_body(reader, limit=4096 - len(body), timeout=timeout)
        candidate = body.decode("latin1", errors="replace").strip().split()
        for token in reversed(candidate):
            try:
                return str(ipaddress.ip_address(token.strip()))
            except ValueError:
                continue
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    return None


async def classify_one(ip: str, port: int, timeout: float = 2.0,
                       rotate_probes: int = 3) -> Verdict:
    """Tek uç: protokol tespiti + egress + v6/rotate kovası."""
    import time
    started = time.monotonic()
    v = Verdict(ip=ip, port=port)

    # 1) HTTP-FWD (en hızlı eleme)
    ok, egress = await _http_fwd_probe(ip, port, EGRESS_HOSTS[0], timeout)
    if ok:
        v.protocol = "http_fwd"
        v.egress_ip = egress
    else:
        # 2) Tünel protokolleri sırayla
        for proto in ("http_con", "socks5", "socks4", "socks4a"):
            tun = await _connect_tunnel(ip, port, EGRESS_HOSTS[0], timeout, proto)
            if tun is None:
                continue
            reader, writer = tun
            egress = await _egress_via_tunnel(reader, writer, EGRESS_HOSTS[0], timeout)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            if egress:
                v.protocol = proto
                v.egress_ip = egress
                break

    if not v.protocol:
        v.latency_ms = (time.monotonic() - started) * 1000
        return v

    v.alive = True
    v.latency_ms = (time.monotonic() - started) * 1000

    # 3) v6 kontrolü — egress IPv6 ise altın kategori
    if v.egress_ip and ":" in v.egress_ip:
        v.bucket = "v6_forward"
        return v

    # 4) Rotate kontrolü — ardışık isteklerde egress değişiyor mu
    if rotate_probes > 1 and v.protocol != "http_fwd":
        seen = {v.egress_ip} if v.egress_ip else set()
        for _ in range(rotate_probes - 1):
            tun = await _connect_tunnel(ip, port, EGRESS_HOSTS[0], timeout, v.protocol)
            if tun is None:
                break
            reader, writer = tun
            eg = await _egress_via_tunnel(reader, writer, EGRESS_HOSTS[0], timeout)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            if eg:
                seen.add(eg)
            if len(seen) > 1:
                v.bucket = "rotate"
                return v

    v.bucket = "v4_forward" if v.protocol == "http_fwd" else v.protocol
    return v


async def classify_batch(endpoints: list[tuple[str, int]], concurrency: int = 500,
                         timeout: float = 2.0) -> list[Verdict]:
    """1000 eşzamanlı asenkron L7 sondası (Yapı Taşı 7)."""
    sem = asyncio.Semaphore(concurrency)

    async def guarded(ip: str, port: int) -> Verdict:
        async with sem:
            return await classify_one(ip, port, timeout)

    return await asyncio.gather(*(guarded(ip, p) for ip, p in endpoints))


def bucket_files(verdicts: list[Verdict]) -> dict[str, list[str]]:
    """Kovaya göre saf ip:port listeleri — dosya adında tür, içerikte sadece uç."""
    out: dict[str, list[str]] = {}
    for v in verdicts:
        if not v.alive or not v.bucket:
            continue
        out.setdefault(f"{v.bucket}.txt", []).append(f"{v.ip}:{v.port}")
    return out
