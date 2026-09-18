#!/usr/bin/env python3
"""ALL-TYPE PROXY CHECKER — xRisky "Proxy Checker v2 [All Type]" davranışının
birebir uyarlaması (underground standardı; cracking.org / crackia / patched.to).

Kaynak metodoloji:
  - xRisky Proxy Checker v2 [All Type]:
      * Tüm tipler: HTTP, SOCKS4, SOCKS5 (auto-detect)
      * Ayarlanabilir timeout ve thread (eşzamanlılık) sayısı
      * Opsiyonel "Site" check — proxy'yi belirli bir siteye karşı doğrula
      * OpenBullet tarzı gerçek istek doğrulaması (varsayılan: Google-benzeri nötr uç)
  - TheSpeedX/socker — SOCKS el sıkışma byte'ları (birebir):
      SOCKS4: \\x04\\x01 + port + ip + \\x00 → yanıt [0]==0x00 ve [1]==0x5A
      SOCKS5: \\x05\\x01\\x00 → yanıt \\x05\\x00
  - monosans/proxy-scraper-checker — doğrulama şekli: check_url'e gerçek istek,
      gövdeden exit IP, gecikme = toplam istek süresi, connect 5s / toplam 10s.

Girdi: var/harvest/gen_queue.txt (GENLE çıktısı: ip:port satırları)
Çıktı: teslim kovalarına saf ip:port + var/harvest/checker/part-*.json (zengin veri)
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import struct
import time
from pathlib import Path

# xRisky checker varsayılanları (timeout ms / thread)
CONNECT_TIMEOUT = 5.0     # monosans connect_timeout
TIMEOUT = 10.0            # monosans timeout
CONCURRENCY = 512         # monosans max_concurrent_checks / xRisky thread sayısı

# Doğrulama ucu — varsayılan nötr exit-IP servisi; "Site" check verilirse o kullanılır
CHECK_HOST = "ipv4.icanhazip.com"
CHECK_PATH = "/"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

BUCKET_FOR = {
    "socks5": "socks5.txt",
    "socks4": "socks4.txt",
    "http_connect": "http_connect.txt",
    "http_fwd": "v4_forward.txt",
}


def _extract_ip(body: bytes) -> str | None:
    text = body.decode("latin1", errors="replace")
    for token in reversed(text.replace("<", " ").replace(">", " ").split()):
        try:
            return str(ipaddress.ip_address(token.strip().strip('"')))
        except ValueError:
            continue
    return None


async def _read_http_head(reader, timeout: float) -> bytes:
    buf = b""
    try:
        while b"\r\n\r\n" not in buf and len(buf) < 8192:
            chunk = await asyncio.wait_for(reader.read(1024), timeout)
            if not chunk:
                break
            buf += chunk
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    return buf


async def _read_rest(reader, limit: int, timeout: float) -> bytes:
    buf = b""
    try:
        while len(buf) < limit:
            chunk = await asyncio.wait_for(reader.read(4096), timeout)
            if not chunk:
                break
            buf += chunk
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    return buf


async def _http_get_through(reader, writer, timeout: float, host: str, path: str) -> tuple[bool, str | None]:
    """Tünel içinden GET — yanıt gövdesinden exit IP (monosans metodu)."""
    try:
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
               f"User-Agent: {USER_AGENT}\r\nAccept: */*\r\n"
               "Connection: close\r\n\r\n")
        writer.write(req.encode())
        await asyncio.wait_for(writer.drain(), timeout)
        head = await _read_http_head(reader, timeout)
        if not head.startswith(b"HTTP/"):
            return False, None
        status = head.split(b" ", 2)[1] if b" " in head else b""
        if status.startswith(b"4") or status.startswith(b"5"):
            return False, None
        _, _, body = head.partition(b"\r\n\r\n")
        if len(body) < 7:
            body += await _read_rest(reader, 4096 - len(body), timeout)
        return True, _extract_ip(body)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None


async def _check_socks5(ip: str, port: int, ctimeout: float, timeout: float) -> tuple[bool, str | None]:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), ctimeout)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None
    try:
        # socker birebir: greeting 05 01 00 → 05 00
        writer.write(b"\x05\x01\x00")
        await asyncio.wait_for(writer.drain(), timeout)
        greeting = await asyncio.wait_for(reader.readexactly(2), timeout)
        if greeting != b"\x05\x00":
            return False, None
        hb = CHECK_HOST.encode()
        writer.write(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack("!H", 80))
        await asyncio.wait_for(writer.drain(), timeout)
        reply = await asyncio.wait_for(reader.readexactly(10), timeout)
        if reply[1] != 0x00:
            return False, None
        return await _http_get_through(reader, writer, timeout, CHECK_HOST, CHECK_PATH)
    except (asyncio.TimeoutError, ConnectionError, OSError, asyncio.IncompleteReadError):
        return False, None
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _check_socks4(ip: str, port: int, ctimeout: float, timeout: float) -> tuple[bool, str | None]:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), ctimeout)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None
    try:
        # socker birebir: 04 01 + port + ip + 00 → yanıt [1]==0x5A
        try:
            packed = ipaddress.IPv4Address(CHECK_HOST).packed
            payload = struct.pack("!BBH4s", 4, 1, 80, packed) + b"checker\x00"
        except ipaddress.AddressValueError:
            payload = (struct.pack("!BBH4s", 4, 1, 80, b"\x00\x00\x00\x01")
                       + b"checker\x00" + CHECK_HOST.encode() + b"\x00")
        writer.write(payload)
        await asyncio.wait_for(writer.drain(), timeout)
        reply = await asyncio.wait_for(reader.readexactly(8), timeout)
        if len(reply) < 2 or reply[0] != 0x00 or reply[1] != 0x5A:
            return False, None
        return await _http_get_through(reader, writer, timeout, CHECK_HOST, CHECK_PATH)
    except (asyncio.TimeoutError, ConnectionError, OSError, asyncio.IncompleteReadError):
        return False, None
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _check_http_connect(ip: str, port: int, ctimeout: float, timeout: float) -> tuple[bool, str | None]:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), ctimeout)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None
    try:
        writer.write(f"CONNECT {CHECK_HOST}:80 HTTP/1.1\r\nHost: {CHECK_HOST}:80\r\n\r\n".encode())
        await asyncio.wait_for(writer.drain(), timeout)
        head = await _read_http_head(reader, timeout)
        first = head.split(b"\r\n", 1)[0]
        if b" 200" not in b" " + first + b" ":
            return False, None
        return await _http_get_through(reader, writer, timeout, CHECK_HOST, CHECK_PATH)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _check_http_fwd(ip: str, port: int, ctimeout: float, timeout: float) -> tuple[bool, str | None]:
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), ctimeout)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None
    try:
        req = (f"GET http://{CHECK_HOST}{CHECK_PATH} HTTP/1.1\r\nHost: {CHECK_HOST}\r\n"
               f"User-Agent: {USER_AGENT}\r\nAccept: */*\r\nConnection: close\r\n\r\n")
        writer.write(req.encode())
        await asyncio.wait_for(writer.drain(), timeout)
        head = await _read_http_head(reader, timeout)
        if not head.startswith(b"HTTP/"):
            return False, None
        status = head.split(b" ", 2)[1] if b" " in head else b""
        if status.startswith(b"4") or status.startswith(b"5"):
            return False, None
        _, _, body = head.partition(b"\r\n\r\n")
        if len(body) < 7:
            body += await _read_rest(reader, 4096 - len(body), timeout)
        return True, _extract_ip(body)
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return False, None
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def check_one(endpoint: str, ctimeout: float = CONNECT_TIMEOUT,
                    timeout: float = TIMEOUT) -> dict | None:
    """xRisky 'All Type': sırayla tüm tipleri dene; ilk çalışanı kaydet."""
    host, _, port_s = endpoint.rpartition(":")
    try:
        port = int(port_s)
        ipaddress.IPv4Address(host)
    except (ValueError, ipaddress.AddressValueError):
        return None
    started = time.monotonic()
    for proto, fn in (("socks5", _check_socks5), ("socks4", _check_socks4),
                      ("http_connect", _check_http_connect), ("http_fwd", _check_http_fwd)):
        ok, exit_ip = await fn(host, port, ctimeout, timeout)
        if ok:
            return {
                "endpoint": endpoint,
                "protocol": proto,
                "exit_ip": exit_ip or "",
                "latency_ms": round((time.monotonic() - started) * 1000),
                "ts": int(time.time()),
            }
    return None


def _write_buckets(teslim: Path, checked: list[dict]) -> dict:
    """Protokol kovalarına saf ip:port yaz (kokpit şeması)."""
    buckets: dict[str, set] = {}
    for rec in checked:
        fname = BUCKET_FOR.get(rec["protocol"])
        if not fname:
            continue
        buckets.setdefault(fname, set()).add(rec["endpoint"])
    counts = {}
    for fname, lines in buckets.items():
        path = teslim / fname
        existing = set()
        if path.exists():
            try:
                existing = {ln.strip() for ln in path.read_text().splitlines() if ln.strip()}
            except OSError:
                existing = set()
        merged = existing | lines
        try:
            path.write_text("\n".join(sorted(merged)) + "\n", encoding="utf-8")
        except OSError:
            continue
        counts[fname] = len(merged)
    return counts


def run_batch(workdir: Path, limit: int = 50_000,
              concurrency: int = CONCURRENCY) -> dict:
    """GENLE havuzundan parti al → xRisky checker → kovalar + zengin sonuç."""
    gen = workdir / "var/harvest/gen_queue.txt"
    checked_log = workdir / "var/harvest/checked.txt"
    checker_dir = workdir / "var/harvest/checker"
    teslim = workdir / "var/teslim"
    checker_dir.mkdir(parents=True, exist_ok=True)

    done: set = set()
    if checked_log.exists():
        try:
            done = {ln.strip() for ln in checked_log.read_text(encoding="utf-8").splitlines() if ln.strip()}
        except OSError:
            done = set()

    batch: list[str] = []
    if gen.exists():
        try:
            with gen.open("r", encoding="utf-8") as fh:
                for line in fh:
                    ep = line.strip()
                    if not ep or ep in done:
                        continue
                    batch.append(ep)
                    if len(batch) >= limit:
                        break
        except OSError:
            batch = []

    if not batch:
        return {"checked": 0, "alive": 0, "queue_empty": True, "verified": []}

    async def guarded(ep: str, sem: asyncio.Semaphore) -> dict | None:
        async with sem:
            return await check_one(ep)

    async def run_all():
        sem = asyncio.Semaphore(concurrency)
        out: list = []
        step = 2000  # bellek: 50k coroutine'i tek seferde açma
        for i in range(0, len(batch), step):
            part = batch[i:i + step]
            out.extend(await asyncio.gather(*(guarded(ep, sem) for ep in part)))
        return out

    results = asyncio.run(run_all())
    alive = [r for r in results if r]

    try:
        with checked_log.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(batch) + "\n")
    except OSError:
        pass

    if alive:
        part = checker_dir / f"part-{int(time.time())}.json"
        try:
            part.write_text(json.dumps(alive, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    _write_buckets(teslim, alive)
    return {"checked": len(batch), "alive": len(alive),
            "queue_empty": False, "verified": alive}




if __name__ == "__main__":
    import sys
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    stats = run_batch(root, limit=int(sys.argv[2]) if len(sys.argv) > 2 else 5000)
    print(json.dumps({k: v for k, v in stats.items() if k != "verified"}, ensure_ascii=False))
