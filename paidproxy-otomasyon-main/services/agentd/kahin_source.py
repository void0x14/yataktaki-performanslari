"""Kahin-backed visual source reader used only for myip.ms hunting."""
from __future__ import annotations

import asyncio
import tempfile
import ipaddress
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse


_IPV4 = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")
_CIDR = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}/(?:[0-9]|[12][0-9]|3[0-2])(?![0-9])")
_ASN = re.compile(r"(?i)(?:\bAS|\bASN|aut-num[^0-9]{0,8})([0-9]{1,10})")
Runner = Callable[[str], Awaitable[dict[str, Any]]]


def _json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _facts(text: str) -> dict[str, list[Any]]:
    ips: set[str] = set()
    cidrs: set[str] = set()
    asns: set[int] = set()
    cidr_tokens = set(_CIDR.findall(text))
    for raw in cidr_tokens:
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            continue
        if network.version == 4 and network.is_global:
            cidrs.add(network.with_prefixlen)
    ip_text = text
    for raw in cidr_tokens:
        ip_text = ip_text.replace(raw, " ")
    for raw in _IPV4.findall(ip_text):
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if address.version == 4 and address.is_global:
            ips.add(str(address))
    for raw in _ASN.findall(text):
        value = int(raw)
        if 1 <= value <= 4294967295:
            asns.add(value)
    return {
        "observed_ips": sorted(ips),
        "observed_cidrs": sorted(cidrs),
        "observed_asns": sorted(asns),
    }


def _kahin_root() -> Path:
    candidates = (
        Path.home() / "cdp-kahin-mcp",
        Path.home() / "Belgeler/mcp-projelerim/cdp-kahin-mcp",
        Path("/opt/cdp-kahin-mcp"),
    )
    for candidate in candidates:
        if (candidate / "kahin/oracle.py").is_file():
            return candidate
    raise RuntimeError("Kahin çalışma alanı bulunamadı")


async def _run_kahin(url: str) -> dict[str, Any]:
    root = _kahin_root()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    from kahin import _state as state
    from kahin.tools.pilot import browser_start, extract, navigate, ocr

    if state._current_engine is None:
        started = _json(await browser_start(engine="mirage", headless=True))
        if started.get("error"):
            raise RuntimeError(str(started["error"]))

    navigation = _json(await navigate(url=url, wait_until="domcontentloaded", timeout=30.0))
    if navigation.get("error"):
        raise RuntimeError(str(navigation["error"]))
    assert state._current_engine is not None
    screenshot_bytes = await state._current_engine.screenshot(full_page=True)
    if not screenshot_bytes:
        raise RuntimeError("Kahin ekran görüntüsü üretmedi")
    httpx_logger = logging.getLogger("httpx")
    previous_disabled = httpx_logger.disabled
    httpx_logger.disabled = True
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
            temporary.write(screenshot_bytes)
            temporary_path = temporary.name
        vision = _json(await ocr(image=temporary_path))
    finally:
        if temporary_path:
            Path(temporary_path).unlink(missing_ok=True)
        httpx_logger.disabled = previous_disabled
    if vision.get("error"):
        raise RuntimeError(str(vision["error"]))
    dom = _json(await extract())
    dom_text = str(dom.get("value") or dom.get("result") or dom.get("text") or "")
    return {
        "navigation": navigation,
        "screenshot_bytes": bytes(screenshot_bytes),
        "ocr": vision,
        "dom_text": dom_text,
    }


def collect_myip_source(url: str, runner: Runner | None = None) -> dict[str, Any]:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "myip.ms":
        raise ValueError("Kahin görsel keşfi yalnız myip.ms kabul eder")
    payload = asyncio.run((runner or _run_kahin)(url))
    ocr_payload = payload.get("ocr") if isinstance(payload.get("ocr"), dict) else {}
    ocr_text = str(
        ocr_payload.get("text")
        or ocr_payload.get("fullText")
        or ocr_payload.get("description")
        or ""
    )
    dom_text = str(payload.get("dom_text") or "")
    combined = "\n".join(part for part in (dom_text, ocr_text) if part).strip()
    if not combined:
        raise RuntimeError("Kahin myip.ms sayfasından DOM veya OCR kanıtı üretemedi")
    return {
        "working_note": "Kahin myip.ms yüzeyini Mirage ile gezdi; Google Vision OCR ve DOM kanıtı toplandı.",
        "url": url,
        "status": 200,
        "content_type": "text/visual+ocr",
        "body_preview": combined[:12000],
        "_screenshot_bytes": bytes(payload.get("screenshot_bytes") or b""),
        "source_provenance": "kahin-mirage-google-vision",
        **_facts(combined),
    }
