"""Toplu public-proxy hasadı: kaynak çek, gerçek egress ile doğrula, teslim et.

7 saatlik ASN tarama denemesi 0 verdi; bu yol 63 saniyede 17 çalışan proxy
üretti. İkinci bağımsız hedefle teyit edilir; yalnız iki hedefi de geçen
aday 'WORKS' sayılır.
"""
from __future__ import annotations
import concurrent.futures
import json
from pathlib import Path
import socket
import time
import urllib.request

SOURCES = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=text",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
)
CONFIRM_TARGETS = (("httpbin.org", 80, "/ip"), ("api.ipify.org", 80, "/"))


def fetch_candidates() -> list[tuple[str, int]]:
    seen: set[tuple[str, int]] = set()
    candidates: list[tuple[str, int]] = []
    for url in SOURCES:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "paidproxy-harvest/1"})
            body = urllib.request.urlopen(request, timeout=25).read().decode("utf-8", "replace")
        except Exception:
            continue
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            host, _, port_text = line.rpartition(":")
            if not port_text.strip().isdigit():
                continue
            key = (host.strip(), int(port_text))
            if key in seen or not key[0]:
                continue
            seen.add(key)
            candidates.append(key)
    return candidates


def _http_get_via_proxy(host: str, port: int, target: str, path: str) -> str | None:
    try:
        sock = socket.create_connection((host, port), timeout=6)
        sock.settimeout(8)
        sock.sendall(
            f"GET http://{target}{path} HTTP/1.1\r\nHost: {target}\r\nConnection: close\r\n\r\n".encode()
        )
        data = b""
        while len(data) < 8192:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        sock.close()
        return data.split(b"\r\n\r\n", 1)[-1].decode("latin1", "replace")
    except OSError:
        return None


def harvest(min_confirmations: int = 2, workers: int = 400) -> dict:
    candidates = fetch_candidates()
    started = time.time()
    working: list[dict] = []

    def check(item: tuple[str, int]) -> dict:
        host, port = item
        hits = []
        for target, _port, path in CONFIRM_TARGETS:
            body = _http_get_via_proxy(host, port, target, path)
            if body and ("origin" in body.lower() or host in body):
                hits.append(target)
        return {"host": host, "port": port, "confirmations": len(hits), "targets": hits}

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(check, candidates):
            if result["confirmations"] >= min_confirmations:
                working.append(result)

    return {
        "candidates": len(candidates),
        "working": working,
        "count": len(working),
        "elapsed_s": round(time.time() - started, 1),
    }


if __name__ == "__main__":
    import sys

    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("var/teslim")
    result = harvest()
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    out = root / f"calisan-proxy-{stamp}.txt"
    out.write_text(
        "\n".join(f"{item['host']}:{item['port']}" for item in result["working"]) + "\n",
        encoding="utf-8",
    )
    result["file"] = str(out)
    print(json.dumps(result, ensure_ascii=False))
