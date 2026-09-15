"""Kahin-backed visual source reader used only for myip.ms hunting."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse


_IPV4 = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")
_CIDR = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}/(?:[0-9]|[12][0-9]|3[0-2])(?![0-9])")
_ASN = re.compile(r"(?i)(?:\bAS|\bASN|aut-num[^0-9]{0,8})([0-9]{1,10})")
_OWNER_SECTION = re.compile(r"(?i)(all\s+)?owner\s+ip\s+ranges?")
_OTHER_SITES = re.compile(r"(?i)other\s+sites\s+on\s+ip")
_RANGE_PAIR = re.compile(
    r"(?<![0-9.])((?:[0-9]{1,3}\.){3}[0-9]{1,3})\s*(?:-|–|—|~|to)\s*"
    r"((?:[0-9]{1,3}\.){3}[0-9]{1,3})(?![0-9.])",
    re.IGNORECASE,
)
_ENGINE_DEAD_CODES = frozenset({
    "engine_dead",
    "engine_unavailable",
    "engine_health_timeout",
    "engine_degraded",
    "connection_lost",
})
_ENGINE_DEAD_MARKERS = (
    "browser engine is dead",
    "engine is dead",
    "engine_dead",
    "connection lost",
    "no browser engine running",
)
_DISCOVERY_JS = (
    "(() => {"
    "const out = {owner_pages: [], other_sites: [], url_go: []};"
    "const add = (arr, v) => { if (v && arr.indexOf(v) < 0) arr.push(v); };"
    "document.querySelectorAll('a[href]').forEach(a => {"
    "const href = String(a.href || '');"
    "if (href.indexOf('/view/ip_owners/') >= 0) add(out.owner_pages, href);"
    "});"
    "document.querySelectorAll('a[href], button, input').forEach(el => {"
    "const text = String(el.textContent || el.value || '').replace(/\\s+/g, ' ').trim();"
    "const onclick = el.getAttribute ? String(el.getAttribute('onclick') || '') : '';"
    "if (/other\\s+sites\\s+on\\s+ip/i.test(text) || /other\\s+sites\\s+on\\s+ip/i.test(onclick)) {"
    "out.other_sites.push({tag: el.tagName, text: text.slice(0, 120), href: String(el.href || ''), onclick: onclick.slice(0, 400)});"
    "}"
    "});"
    "const html = String(document.documentElement.innerHTML || '');"
    "const re = /\\$\\.url\\.go\\(\\s*[\"']([^\"']+)[\"']\\s*\\)/g;"
    "let m, guard = 0;"
    "while ((m = re.exec(html)) !== null && guard++ < 500) add(out.url_go, m[1]);"
    "out.other_sites = out.other_sites.slice(0, 20);"
    "out.owner_pages = out.owner_pages.slice(0, 20);"
    "return JSON.stringify(out);"
    "})()"
)
_RANGES_JS = (
    "(() => {"
    "const out = {ranges: [], next: null, title: String(document.title || ''), url: String(location.href)};"
    "document.querySelectorAll(\"a[href*='/view/ip_ranges/']\").forEach(a => {"
    "out.ranges.push({href: String(a.href || ''), text: String(a.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120)});"
    "});"
    "const current = String(location.href);"
    "const pageMatch = current.match(/\\/(\\d+)\\/?$/);"
    "const page = pageMatch ? parseInt(pageMatch[1], 10) : null;"
    "let best = null, bestPage = null;"
    "document.querySelectorAll('a[href]').forEach(a => {"
    "const href = String(a.href || '');"
    "if (href.indexOf('/browse/ip_ranges/') < 0) return;"
    "const mm = href.match(/^(.*\\/)(\\d+)\\/?$/);"
    "if (!mm) return;"
    "const n = parseInt(mm[2], 10);"
    "if (page !== null && n <= page) return;"
    "if (bestPage === null || n < bestPage) { bestPage = n; best = href; }"
    "});"
    "out.next = best;"
    "out.human_verification = /human\\s+verification|prove\\s+you'?re\\s+not\\s+a\\s+robot/i.test(out.title);"
    "return JSON.stringify(out);"
    "})()"
)
_OWNER_META_JS = (
    "(() => {"
    "const out = {tables: []};"
    "const re = /^ip_ranges_detailstbl\\d+_bottom$/;"
    "document.querySelectorAll(\"[id^='ip_ranges_detailstbl']\").forEach(marker => {"
    "if (!re.test(marker.id)) return;"
    "const box = marker.parentElement;"
    "const text = String((box && box.innerText) || '').replace(/\\s+/g, ' ').trim();"
    "const total = (text.match(/Total:\\s*(\\d+)\\s*records/i) || [])[1] || null;"
    "const shown = (text.match(/show first\\s*(\\d+)\\s*records/i) || [])[1] || null;"
    "let allRecords = null;"
    "if (box) {"
    "box.querySelectorAll('a[href]').forEach(a => {"
    "const href = String(a.href || '');"
    "if (/\\/browse\\/ip_ranges\\/\\d+\\/ownerID\\//.test(href)) allRecords = href;"
    "});"
    "}"
    "const links = [];"
    "const scope = marker.closest('li') || document;"
    "scope.querySelectorAll(\"a[href*='/view/ip_ranges/']\").forEach(a => links.push(String(a.href || '')));"
    "out.tables.push({id: marker.id, total: total, shown: shown, all_records: allRecords, links: links.slice(0, 2000)});"
    "});"
    "return JSON.stringify(out);"
    "})()"
)
Runner = Callable[[str], Awaitable[dict[str, Any]]]
_LOOP: asyncio.AbstractEventLoop | None = None


def _event_loop() -> asyncio.AbstractEventLoop:
    """One long-lived loop keeps the Kahin stdio transport usable.

    ``asyncio.run`` per call closes the loop the Mirage subprocess transport is
    bound to; the next call then sees a dead engine even though the sidecar is
    still running. A persistent loop makes the engine genuinely reusable and
    makes a real death detectable through the normal health probe.
    """
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


def _run(coro: Awaitable[Any]) -> Any:
    return _event_loop().run_until_complete(coro)


class EngineDead(RuntimeError):
    """A Kahin call failed because the browser engine itself died."""

    def __init__(self, payload: dict[str, Any]):
        super().__init__(str(payload.get("error") or payload.get("code") or "browser engine dead"))
        self.payload = payload


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


def _cidrs_from_pair(start: str, end: str) -> list[str]:
    try:
        first = ipaddress.ip_address(start)
        last = ipaddress.ip_address(end)
    except ValueError:
        return []
    if first.version != 4 or last.version != 4 or int(last) < int(first):
        return []
    out: list[str] = []
    for network in ipaddress.summarize_address_range(first, last):
        if network.version == 4 and network.is_global:
            out.append(network.with_prefixlen)
    return out


def _ranges_in_text(text: str) -> list[tuple[str, str]]:
    """Normalize CIDR and start-end owner ranges into CIDR entries."""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(cidrs: list[str], how: str) -> None:
        for cidr in cidrs:
            if cidr not in seen:
                seen.add(cidr)
                found.append((cidr, how))

    for raw in _CIDR.findall(text):
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            continue
        if network.version == 4 and network.is_global:
            add([network.with_prefixlen], "cidr")
    for match in _RANGE_PAIR.finditer(text):
        add(_cidrs_from_pair(match.group(1), match.group(2)), "start-end")
    if not found:
        # OCR sometimes drops the dash; pair the IPv4 tokens in reading order.
        tokens = _IPV4.findall(text)
        if len(tokens) >= 2 and len(tokens) % 2 == 0:
            for index in range(0, len(tokens), 2):
                add(_cidrs_from_pair(tokens[index], tokens[index + 1]), "paired-ipv4")
    return found


_RANGE_HREF = re.compile(
    r"/view/ip_ranges/\d+/((?:[0-9]{1,3}\.){3}[0-9]{1,3})_((?:[0-9]{1,3}\.){3}[0-9]{1,3})"
)
_URL_GO = re.compile(r"\$\.url\.go\(\s*[\"']([^\"']+)[\"']\s*\)")


def _ranges_from_hrefs(links: Any) -> list[tuple[str, str]]:
    """Extract owner ranges from myip.ms /view/ip_ranges/<id>/<start>_<end> links."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    if not isinstance(links, list):
        return out
    for link in links:
        href = str((link or {}).get("href") or "") if isinstance(link, dict) else str(link or "")
        match = _RANGE_HREF.search(href)
        if match is None:
            continue
        for cidr in _cidrs_from_pair(match.group(1), match.group(2)):
            if cidr not in seen:
                seen.add(cidr)
                out.append((cidr, "href"))
    return out


def _url_go_targets(text: Any) -> list[str]:
    return _URL_GO.findall(str(text or ""))


def _absolute_myip(target: Any) -> str:
    value = str(target or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    if value.startswith("/"):
        return "https://myip.ms" + value
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.hostname == "myip.ms":
        return value
    return ""


def _discover_targets(raw: Any) -> dict[str, Any]:
    """Map myip.ms anchors/buttons to the owner page and Other Sites on IP page."""
    data = raw if isinstance(raw, dict) else _json(raw)
    owner_pages: list[str] = []
    for value in data.get("owner_pages") or []:
        url = _absolute_myip(value)
        if url and url not in owner_pages:
            owner_pages.append(url)
    other_sites = ""
    for entry in data.get("other_sites") or []:
        if not isinstance(entry, dict):
            continue
        candidates = [entry.get("href"), entry.get("onclick"), entry.get("text")]
        for candidate in candidates:
            for target in [candidate, *_url_go_targets(candidate)]:
                url = _absolute_myip(target)
                if url:
                    other_sites = url
                    break
            if other_sites:
                break
        if other_sites:
            break
    if not other_sites:
        for target in data.get("url_go") or []:
            url = _absolute_myip(target)
            if url and ("/view/ip_addresses/" in url or "/view/comp_ip/" in url):
                other_sites = url
                break
    return {
        "owner_page_url": owner_pages[0] if owner_pages else None,
        "owner_pages": owner_pages,
        "other_sites_on_ip": other_sites or None,
        "url_go": list(data.get("url_go") or []),
    }


def _is_human_verification(title: Any, text: Any) -> bool:
    blob = f"{title or ''} {text or ''}"
    return bool(re.search(r"human\s+verification|prove\s+you'?re\s+not\s+a\s+robot", blob, re.IGNORECASE))


def _merge_range_lists(
    owner: dict[str, Any], lists: list[tuple[Any, str]]
) -> dict[str, Any]:
    ranges = list(owner.get("owner_ranges") or [])
    provenance = list(owner.get("provenance") or [])
    for links, source in lists:
        for cidr, how in _ranges_from_hrefs(links):
            if cidr not in ranges:
                ranges.append(cidr)
            provenance.append(
                {"cidr": cidr, "source": source, "section": "page_ranges", "match": how}
            )
    return {**owner, "owner_ranges": ranges, "provenance": provenance}


def _owner_sections(text: str) -> list[tuple[str, str]]:
    """Return (section_name, window) for every owner-range label on the page."""
    matches = list(_OWNER_SECTION.finditer(text))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        is_all = bool(match.group(1))
        start = match.end()
        stop = min(len(text), start + (6000 if is_all else 500))
        if index + 1 < len(matches):
            stop = min(stop, matches[index + 1].start())
        other = _OTHER_SITES.search(text, start)
        if other is not None:
            stop = min(stop, other.start())
        if not is_all:
            blank = re.search(r"\n\s*\n", text[start:stop])
            if blank is not None:
                stop = start + blank.start()
        sections.append(("all_owner_ip_ranges" if is_all else "owner_ip_range", text[start:stop]))
    return sections


def _extract_owner_fields(text: str, source: str, labeled: bool = True) -> dict[str, Any]:
    primary: list[str] = []
    ranges: list[str] = []
    provenance: list[dict[str, str]] = []
    windows = _owner_sections(text) if labeled else [("page_ranges", text)]
    for section, window in windows:
        for cidr, how in _ranges_in_text(window):
            if section == "owner_ip_range" and cidr not in primary:
                primary.append(cidr)
            if cidr not in ranges:
                ranges.append(cidr)
            provenance.append({"cidr": cidr, "source": source, "section": section, "match": how})
    return {"owner_range_primary": primary, "owner_ranges": ranges, "provenance": provenance}


def _merge_owner_fields(texts: list[tuple[Any, ...]]) -> dict[str, Any]:
    primary: list[str] = []
    ranges: list[str] = []
    provenance: list[dict[str, str]] = []
    for item in texts:
        text, source = str(item[0] or ""), str(item[1] or "")
        labeled = bool(item[2]) if len(item) > 2 else True
        if not text:
            continue
        fields = _extract_owner_fields(text, source, labeled=labeled)
        for cidr in fields["owner_range_primary"]:
            if cidr not in primary:
                primary.append(cidr)
        for cidr in fields["owner_ranges"]:
            if cidr not in ranges:
                ranges.append(cidr)
        provenance.extend(fields["provenance"])
    return {"owner_range_primary": primary, "owner_ranges": ranges, "provenance": provenance}


def _looks_engine_dead(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    code = str(payload.get("code") or "").strip().lower()
    if code in _ENGINE_DEAD_CODES:
        return True
    error = str(payload.get("error") or "").strip().lower()
    return any(marker in error for marker in _ENGINE_DEAD_MARKERS)


async def _probe_engine(engine_health: Callable[[], Awaitable[str]]) -> dict[str, Any]:
    try:
        raw = await engine_health()
    except Exception as exc:  # noqa: BLE001 - a failed probe is engine evidence
        return {"alive": False, "state": "probe_error", "error": f"{type(exc).__name__}: {exc}"}
    payload = _json(raw)
    if not payload:
        return {"alive": False, "state": "probe_unparseable", "error": str(raw)[:500]}
    if payload.get("error") and "alive" not in payload:
        payload["alive"] = False
    return payload


def _engine_usable(health: dict[str, Any]) -> bool:
    return health.get("alive") is True


def _death_record(health: dict[str, Any], state: Any) -> dict[str, Any]:
    last = health.get("last_engine_death")
    if last is None:
        last = getattr(state, "_last_engine_death", None)
    return {
        "reason": health.get("reason") or health.get("error") or health.get("state"),
        "state": health.get("state"),
        "error": health.get("error"),
        "code": health.get("code"),
        "stderr_log": health.get("stderr_log"),
        "last_engine_death": last,
    }


async def _recover_engine(
    browser_start: Callable[..., Awaitable[str]],
    browser_stop: Callable[[], Awaitable[str]],
    engine_health: Callable[[], Awaitable[str]],
    recovery: dict[str, Any],
    *,
    force: bool = False,
    crash: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Probe the engine; on death/degradation stop and start it again."""
    from kahin import _state as state

    health = await _probe_engine(engine_health)
    recovery["last_probe"] = health
    if _engine_usable(health) and not force:
        return health
    recovery["recoveries"] = int(recovery.get("recoveries") or 0) + 1
    recovery["last_crash"] = crash or _death_record(health, state)
    try:
        stopped = _json(await browser_stop())
    except Exception as exc:  # noqa: BLE001 - a failed stop must not block the restart
        stopped = {"error": f"{type(exc).__name__}: {exc}", "code": "engine_stop_failed"}
    if stopped.get("error") and str(stopped.get("code") or "") != "engine_unavailable":
        recovery["stop_error"] = str(stopped.get("error"))
    try:
        started = _json(await browser_start(engine="mirage", headless=True))
    except Exception as exc:  # noqa: BLE001 - report the real start failure
        raise RuntimeError(f"Browser engine toparlanamadı: {type(exc).__name__}: {exc}") from exc
    if started.get("error"):
        raise RuntimeError(f"Browser engine toparlanamadı: {started['error']}")
    recovery["restarts"] = int(recovery.get("restarts") or 0) + 1
    health_after = await _probe_engine(engine_health)
    recovery["last_probe"] = health_after
    if not _engine_usable(health_after):
        raise RuntimeError(
            "Browser engine toparlanamadı: "
            + str(health_after.get("error") or health_after.get("state") or health_after)
        )
    return health_after


def _evaluate_value(raw: Any) -> Any:
    payload = raw if isinstance(raw, dict) else _json(raw)
    result = payload.get("result")
    value = result.get("value") if isinstance(result, dict) else payload.get("value")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


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
    from kahin.tools.engine import engine_health
    from kahin.tools.pilot import browser_start, browser_stop, evaluate, extract, navigate, ocr

    recovery: dict[str, Any] = {
        "recoveries": 0,
        "restarts": 0,
        "last_crash": None,
        "last_probe": None,
    }
    if state._current_engine is None:
        started = _json(await browser_start(engine="mirage", headless=True))
        if started.get("error"):
            raise RuntimeError(str(started["error"]))
    await _recover_engine(browser_start, browser_stop, engine_health, recovery)

    async def _capture(target_url: str) -> dict[str, Any]:
        navigation = _json(await navigate(url=target_url, wait_until="domcontentloaded", timeout=30.0))
        if navigation.get("error"):
            if _looks_engine_dead(navigation):
                raise EngineDead(navigation)
            raise RuntimeError(str(navigation["error"]))
        if state._current_engine is None:
            raise EngineDead({"error": "Browser engine is dead (crashed).", "code": "engine_dead"})
        try:
            screenshot_bytes = await state._current_engine.screenshot(full_page=True)
        except Exception as exc:  # noqa: BLE001 - engine death surfaces as a raw error
            payload = {"error": f"{type(exc).__name__}: {exc}", "code": str(getattr(exc, "code", "") or "")}
            if _looks_engine_dead(payload):
                raise EngineDead(payload) from exc
            raise
        if not screenshot_bytes:
            raise EngineDead({"error": "Kahin ekran görüntüsü üretmedi", "code": "engine_screenshot_empty"})
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
            if _looks_engine_dead(vision):
                raise EngineDead(vision)
            raise RuntimeError(str(vision["error"]))
        dom = _json(await extract())
        dom_text = str(dom.get("value") or dom.get("result") or dom.get("text") or "")
        if _is_human_verification("", dom_text):
            # OPERATOR ORDER: kahin's own tools clear the myip.ms wall.
            # captcha.php resmini Vision OCR'ye gönder, çıkan metni kutuya yaz,
            # gönder düğmesine bas. Yerleşik pilot/mirage araçları; elle JS yok.
            from kahin.tools.pilot_mirage import mirage_click, mirage_get_attribute, mirage_type

            img_src = ""
            attr = _json(await mirage_get_attribute(selector="img[src*='captcha.php']", name="src"))
            img_src = str(attr.get("value") or "")
            if img_src:
                captcha_url = img_src if img_src.startswith("http") else "https://myip.ms" + ("/" + img_src.lstrip("/") if not img_src.startswith("/") else img_src)
                await navigate(url=captcha_url, wait_until="load", timeout=30.0)
                cap_shot = await state._current_engine.screenshot(full_page=False)
                cap_tmp = ""
                answer = ""
                try:
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as cap_file:
                        cap_file.write(bytes(cap_shot))
                        cap_tmp = cap_file.name
                    cap_vision = _json(await ocr(image=cap_tmp))
                    for key in ("text", "fullText", "description"):
                        blob = str(cap_vision.get(key) or "")
                        if blob:
                            answer = re.sub(r"[^A-Za-z0-9]", "", blob)
                            break
                finally:
                    if cap_tmp:
                        Path(cap_tmp).unlink(missing_ok=True)
                if answer:
                    await navigate(url=target_url, wait_until="domcontentloaded", timeout=30.0)
                    await mirage_type(selector="#p_captcha_response", text=answer)
                    await mirage_click(selector="#captcha_submit")
                    await asyncio.sleep(3.0)
                    try:
                        screenshot_bytes = await state._current_engine.screenshot(full_page=True)
                    except Exception:
                        pass
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
                        temporary.write(bytes(screenshot_bytes))
                        retry_tmp = temporary.name
                    try:
                        vision = _json(await ocr(image=retry_tmp))
                    finally:
                        Path(retry_tmp).unlink(missing_ok=True)
                    dom = _json(await extract())
                    dom_text = str(dom.get("value") or dom.get("result") or dom.get("text") or "")
        discovery: dict[str, Any] = {}
        try:
            discovery = _discover_targets(_evaluate_value(await evaluate(_DISCOVERY_JS)))
        except Exception as exc:  # noqa: BLE001 - link discovery is optional
            recovery["link_probe_error"] = f"{type(exc).__name__}: {exc}"
        return {
            "navigation": navigation,
            "screenshot_bytes": bytes(screenshot_bytes),
            "ocr": vision,
            "dom_text": dom_text,
            "owner_page_url": discovery.get("owner_page_url"),
            "other_sites_on_ip": discovery.get("other_sites_on_ip"),
            "url_go": discovery.get("url_go") or [],
        }

    async def _capture_text(target_url: str, meta: bool = False) -> dict[str, Any]:
        navigation = _json(await navigate(url=target_url, wait_until="domcontentloaded", timeout=30.0))
        if navigation.get("error"):
            if _looks_engine_dead(navigation):
                raise EngineDead(navigation)
            raise RuntimeError(str(navigation["error"]))
        dom = _json(await extract())
        text = str(dom.get("value") or dom.get("result") or dom.get("text") or "")
        title = ""
        try:
            title = str(_evaluate_value(await evaluate("String(document.title || '')")) or "")
        except Exception as exc:  # noqa: BLE001 - title is diagnostic, not fatal
            recovery["title_probe_error"] = f"{type(exc).__name__}: {exc}"
        ranges: Any = []
        next_url: Any = None
        human = _is_human_verification(title, text)
        try:
            probe = _evaluate_value(await evaluate(_RANGES_JS))
        except Exception as exc:  # noqa: BLE001 - href ranges are an extra evidence path
            recovery["ranges_probe_error"] = f"{type(exc).__name__}: {exc}"
            probe = None
        if isinstance(probe, dict):
            ranges = probe.get("ranges") or []
            next_url = probe.get("next")
            title = title or str(probe.get("title") or "")
            human = human or bool(probe.get("human_verification"))
        owner_meta: Any = {}
        if meta:
            try:
                owner_meta = _evaluate_value(await evaluate(_OWNER_META_JS)) or {}
            except Exception as exc:  # noqa: BLE001 - totals are an extra evidence path
                recovery["owner_meta_error"] = f"{type(exc).__name__}: {exc}"
                owner_meta = {}
        return {
            "text": text,
            "title": title,
            "ranges": ranges if isinstance(ranges, list) else [],
            "next": next_url,
            "human_verification": human,
            "owner_meta": owner_meta if isinstance(owner_meta, dict) else {},
        }

    async def _with_recovery(call: Callable[[], Awaitable[Any]]) -> Any:
        try:
            return await call()
        except EngineDead as exc:
            await _recover_engine(
                browser_start,
                browser_stop,
                engine_health,
                recovery,
                force=True,
                crash=_death_record(exc.payload, state),
            )
            return await call()

    primary = await _with_recovery(lambda: _capture(url))
    owner_page_url = primary.get("owner_page_url")
    owner_page_text = ""
    owner_page_title = ""
    owner_page_ranges: Any = []
    owner_meta: dict[str, Any] = {}
    if owner_page_url:
        try:
            page = await _with_recovery(lambda: _capture_text(str(owner_page_url), True))
            owner_page_text = str(page.get("text") or "")
            owner_page_title = str(page.get("title") or "")
            owner_page_ranges = page.get("ranges") or []
            owner_meta = page.get("owner_meta") if isinstance(page.get("owner_meta"), dict) else {}
        except Exception as exc:  # noqa: BLE001 - primary page evidence is kept
            recovery["owner_page_error"] = f"{type(exc).__name__}: {exc}"

    ranges_table: dict[str, Any] = {}
    for table in owner_meta.get("tables") or []:
        if isinstance(table, dict):
            ranges_table = table
            break
    ranges_total: Any = ranges_table.get("total")
    try:
        ranges_total = int(ranges_total) if ranges_total is not None else None
    except (TypeError, ValueError):
        ranges_total = None
    ranges_shown: Any = ranges_table.get("shown")
    try:
        ranges_shown = int(ranges_shown) if ranges_shown is not None else None
    except (TypeError, ValueError):
        ranges_shown = None
    all_records_url = ranges_table.get("all_records")
    all_records_blocked = False
    all_records_ranges: list[Any] = []
    all_records_pages: list[dict[str, Any]] = []
    if all_records_url:
        seen_urls: set[str] = set()
        current_url = str(all_records_url)
        for _ in range(50):
            if not current_url or current_url in seen_urls:
                break
            seen_urls.add(current_url)
            try:
                page = await _with_recovery(lambda: _capture_text(str(current_url)))
            except Exception as exc:  # noqa: BLE001 - owner page evidence is kept
                recovery["all_records_error"] = f"{type(exc).__name__}: {exc}"
                break
            title = str(page.get("title") or "")
            blocked = bool(page.get("human_verification")) or _is_human_verification(
                title, page.get("text")
            )
            page_ranges = page.get("ranges") or []
            all_records_pages.append(
                {
                    "url": current_url,
                    "title": title,
                    "blocked": blocked,
                    "range_links": len(page_ranges),
                }
            )
            if blocked:
                all_records_blocked = True
                break
            all_records_ranges.extend(page_ranges)
            current_url = str(page.get("next") or "")

    other_sites_url = primary.get("other_sites_on_ip")
    other_sites_text = ""
    other_sites_title = ""
    other_sites_ranges: Any = []
    if other_sites_url:
        try:
            page = await _with_recovery(lambda: _capture_text(str(other_sites_url)))
            other_sites_text = str(page.get("text") or "")
            other_sites_title = str(page.get("title") or "")
            other_sites_ranges = page.get("ranges") or []
        except Exception as exc:  # noqa: BLE001 - primary page evidence is kept
            recovery["other_sites_error"] = f"{type(exc).__name__}: {exc}"
    return {
        "navigation": primary["navigation"],
        "screenshot_bytes": primary["screenshot_bytes"],
        "ocr": primary["ocr"],
        "dom_text": primary["dom_text"],
        "owner_page_url": owner_page_url,
        "owner_page_title": owner_page_title,
        "owner_page_text": owner_page_text,
        "owner_page_ranges": owner_page_ranges,
        "owner_ranges_total": ranges_total,
        "owner_ranges_shown": ranges_shown,
        "owner_ranges_all_records_url": all_records_url,
        "owner_ranges_all_records_blocked": all_records_blocked,
        "owner_ranges_all_records_pages": all_records_pages,
        "owner_all_records_ranges": all_records_ranges,
        "other_sites_on_ip": other_sites_url,
        "other_sites_title": other_sites_title,
        "other_sites_text": other_sites_text,
        "other_sites_ranges": other_sites_ranges,
        "engine_recovery": recovery,
    }


def collect_myip_source(url: str, runner: Runner | None = None) -> dict[str, Any]:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "myip.ms":
        raise ValueError("Kahin görsel keşfi yalnız myip.ms kabul eder")
    payload = _run((runner or _run_kahin)(url))
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
    owner = _merge_owner_fields(
        [
            (dom_text, "dom", True),
            (ocr_text, "ocr", True),
            (str(payload.get("owner_page_text") or ""), "owner_page", False),
            (str(payload.get("other_sites_text") or ""), "other_sites_on_ip", False),
        ]
    )
    owner = _merge_range_lists(
        owner,
        [
            (payload.get("owner_page_ranges"), "owner_page"),
            (payload.get("owner_all_records_ranges"), "owner_all_records"),
            (payload.get("other_sites_ranges"), "other_sites_on_ip"),
        ],
    )
    ranges_total = payload.get("owner_ranges_total")
    ranges_missing = None
    if isinstance(ranges_total, int):
        ranges_missing = max(0, ranges_total - len(owner["owner_ranges"]))
    return {
        "working_note": "Kahin myip.ms yüzeyini Mirage ile gezdi; Google Vision OCR ve DOM kanıtı toplandı.",
        "url": url,
        "status": 200,
        "content_type": "text/visual+ocr",
        "body_preview": combined[:12000],
        "_screenshot_bytes": bytes(payload.get("screenshot_bytes") or b""),
        "source_provenance": "kahin-mirage-google-vision",
        **_facts(combined),
        "owner_range_primary": owner["owner_range_primary"],
        "owner_ranges": owner["owner_ranges"],
        "owner_ranges_provenance": owner["provenance"],
        "owner_page_url": payload.get("owner_page_url"),
        "owner_page_title": payload.get("owner_page_title"),
        "other_sites_on_ip": payload.get("other_sites_on_ip"),
        "other_sites_title": payload.get("other_sites_title"),
        "other_sites_human_verification": _is_human_verification(
            payload.get("other_sites_title"), payload.get("other_sites_text")
        ),
        "owner_ranges_total": ranges_total,
        "owner_ranges_shown": payload.get("owner_ranges_shown"),
        "owner_ranges_collected": len(owner["owner_ranges"]),
        "owner_ranges_missing": ranges_missing,
        "owner_ranges_all_records_url": payload.get("owner_ranges_all_records_url"),
        "owner_ranges_all_records_blocked": payload.get(
            "owner_ranges_all_records_blocked", False
        ),
        "owner_ranges_pages": payload.get("owner_ranges_all_records_pages") or [],
        "engine_recovery": payload.get("engine_recovery")
        or {"recoveries": 0, "restarts": 0, "last_crash": None},
    }
