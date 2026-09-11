"""VDS üzerinde AI-native gözlem, araç seçimi ve proxy kanıt döngüsü.

Bu modül sabit tarama hattı çalıştırmaz. Her döngüde mevcut kanıtı AI'ye
gösterir; AI araç adı ve hedef bağlamını seçer. Araçlar yalnız VDS worker
prosesinde çalışır ve her sonuç olay + kalıcı çıktı referansı ile görünür.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import socket
import subprocess
import time
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from proxy_pipeline.tarama_plani import bant_listesi


_CLAUDE_PLANNER_TIMEOUT = 240


def _claude_planner_binary() -> str | None:
    """Locate the Claude Code harness (the planner), if installed."""
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "claude"
    return str(fallback) if fallback.is_file() else None


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Pull the first balanced JSON object out of planner output."""
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}":
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        parsed = json.loads(text[start:index + 1])
                    except json.JSONDecodeError:
                        start = -1
                        continue
                    if isinstance(parsed, dict):
                        return parsed
                    start = -1
    return None


def _sanitize_for_snapshot(data: Any, max_list: int = 30) -> Any:
    """Sanitize snapshot payload so huge port lists or dumps don't bloat the prompt."""
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            if (
                key in {"open_ports", "masscan_reported", "ports", "probed_ports", "already_validated_ports"}
                and isinstance(value, list)
                and len(value) > max_list
            ):
                sanitized[key] = value[:max_list]
                sanitized[f"{key}_sample_count"] = max_list
                sanitized[f"{key}_total_count"] = len(value)
            else:
                sanitized[key] = _sanitize_for_snapshot(value, max_list=max_list)
        return sanitized
    elif isinstance(data, list):
        if len(data) > max_list and all(isinstance(x, (int, str)) for x in data):
            return [_sanitize_for_snapshot(x, max_list=max_list) for x in data[:max_list]]
        return [_sanitize_for_snapshot(x, max_list=max_list) for x in data]
    return data


def claude_planner_decide(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Ask the Claude Code harness for the next hunt decision.

    The harness plans; this runtime executes the chosen tools. No separate
    Python decision loop is introduced.
    """
    binary = _claude_planner_binary()
    if not binary:
        raise RuntimeError("claude harness bulunamadı")
    sanitized_snapshot = _sanitize_for_snapshot(snapshot)
    snapshot_json = json.dumps(sanitized_snapshot, ensure_ascii=False, default=str)
    if len(snapshot_json) > 120000:
        snapshot_json = snapshot_json[:120000]
    prompt = (
        "Sen PaidProxy açık vekil avcısının karar ajanısın. "
        "Aşağıdaki SNAPSHOT gerçek VDS kanıtıdır. Bir sonraki adımı seç. "
        "Yalnızca tek bir JSON nesnesi döndür; açıklama yazma. "
        'Alanlar: action (research|sample|expand|full_scan|defer|drop|reassess|deep_test), '
        "requested_tools (katalogdaki araç adları), "
        "resource_plan.tool_arguments (araç adı -> argüman nesnesi), "
        "evidence, counter_evidence, risks, expected_value, confidence, alternatives. "
        "Kurallar: hedefi gerçek kanıttan türet; kanıtsız hedef uydurma. "
        "Port ve aralık seçimi senin kararın; kod kapısı yok. "
        "L4 canlılık ile L7 çıkışı karıştırma; çıkışsız açık port vekil değildir. "
        "Kan varsa damarda kal, sıfır kan varsa başka kokuya geç.\n\n"
        "SNAPSHOT:\n"
        + snapshot_json
    )
    env = os.environ.copy()
    local_bin = str(Path.home() / ".local" / "bin")
    env["PATH"] = local_bin + os.pathsep + env.get("PATH", "")
    try:
        completed = subprocess.run(
            [binary, "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=_CLAUDE_PLANNER_TIMEOUT,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"claude harness hatası: {type(exc).__name__}: {exc}") from exc
    raw_output = (completed.stdout or "").strip()
    if completed.returncode != 0 and not raw_output:
        raise RuntimeError((completed.stderr or f"claude exit {completed.returncode}").strip()[:500])
    decision = _extract_json_object(raw_output)
    if not isinstance(decision, dict):
        envelope = _extract_json_object(raw_output)
        result = envelope.get("result") if isinstance(envelope, dict) else None
        if isinstance(result, str):
            decision = _extract_json_object(result)
        elif isinstance(result, dict):
            decision = result
    if not isinstance(decision, dict):
        raise RuntimeError("claude harness geçerli JSON karar döndürmedi")
    decision.setdefault("provider", "claude-code")
    decision.setdefault("model", os.environ.get("ANTHROPIC_MODEL", "mimo-v2.5-pro"))
    return decision


CONTROLLED_TOOLS = {
    "observe_vds_surface",
    "browse_public_source",
    "inspect_owner_context",
    "list_owner_ranges",
    "masscan_liveness",
    "port_scan_live_ip",
    "expand_live_ip",
    "validate_proxy",
    "publish_proxy",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _outcome_argument_summary(name: str, arguments: Any) -> dict[str, Any]:
    """Keep the real planner intent, without dumping whole payloads."""
    if not isinstance(arguments, dict):
        return {}
    keys = (
        "cidr",
        "ip",
        "host",
        "port",
        "ports",
        "port_spec",
        "port_range",
        "rate",
        "protocols",
        "target_url",
        "asn",
    )
    return {key: arguments[key] for key in keys if key in arguments}


def _ports_from_spec(value: Any) -> list[int]:
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = str(value or "").replace(";", ",").split(",")
    ports: set[int] = set()
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        if "-" in text:
            left, right = text.split("-", 1)
            try:
                start, end = int(left), int(right)
            except ValueError:
                continue
            ports.update(range(max(1, start), min(65535, end) + 1))
        else:
            try:
                port = int(text)
            except ValueError:
                continue
            if 1 <= port <= 65535:
                ports.add(port)
    return sorted(ports)


def _masscan_has_file_capability(binary: str | None) -> bool:
    """True when masscan carries net capabilities, so no sudo is needed.

    ``NoNewPrivileges=true`` in the agentd unit blocks sudo outright, so the
    file-capability path is the supported way to run L4 from an unprivileged
    worker. ``getcap`` is not installed on every host, so the security.capability
    xattr is read directly.
    """
    if not binary:
        return False
    if hasattr(os, "getxattr"):
        try:
            value = os.getxattr(binary, "security.capability")
        except OSError:
            value = b""
        if value:
            # Effective bit set in the permitted/inheritable/effective words.
            return bool(value[1] & 0x01) or len(value) >= 8
    getcap = shutil.which("getcap")
    if not getcap:
        return False
    try:
        completed = subprocess.run(
            [getcap, binary], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and "cap_net_raw" in (completed.stdout or "").lower()


def _masscan_command(cidr: str, port_spec: str, rate: int) -> list[str]:
    """Build the real L4 command, elevating only when masscan lacks capabilities.

    ``--wait`` and ``--rate`` are execution knobs, not target decisions: they
    come from the operator environment and never restrict which target is hit.
    """
    binary = shutil.which("masscan") or "masscan"
    wait = str(os.environ.get("PAIDPROXY_MASSCAN_WAIT", "0") or "0")
    command = [binary, cidr, "-p", port_spec, "--wait", wait, "-oL", "-", "--rate", str(rate)]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        if _masscan_has_file_capability(binary):
            return command
        sudo = shutil.which("sudo")
        if not sudo:
            raise RuntimeError("masscan için root yetkisi, file capability veya sudo gerekli")
        command = [sudo, "-n", *command]
    return command


def _json_write(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return f"agent://{path.parts[-3]}/{path.relative_to(path.parents[1])}"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

ARGUMENT_CONTRACTS: dict[str, dict[str, Any]] = {
    "observe_vds_surface": {"required": [], "optional": []},
    "browse_public_source": {
        "required": ["url"],
        "optional": ["timeout"],
        "url": "absolute public http/https URL",
    },
    "inspect_owner_context": {"required": ["ip"], "optional": []},
    "list_owner_ranges": {"required": ["asn"], "optional": []},
    "masscan_liveness": {
        "required": ["cidr", "one first port in ports OR port_spec/port_range"],
        "optional": ["rate"],
    },
    "port_scan_live_ip": {
        "required": ["ip"],
        "optional": ["port_range", "timeout", "concurrency"],
    },
    "expand_live_ip": {
        "required": ["ip", "ports OR port_spec/port_range"],
        "optional": ["timeout", "concurrency"],
    },
    "validate_proxy": {
        "required": ["host OR ip", "port", "target_url", "protocols"],
        "target_url": "absolute public http/https URL",
        "protocols": ["http_connect", "socks5", "socks4", "socks4a"],
    },
    "publish_proxy": {
        "required": [
            "validation_ref",
            "host OR ip",
            "port",
            "protocol",
            "quality_label",
            "quality_rationale",
        ],
        "protocols": ["http_connect", "socks5", "socks4", "socks4a"],
    },
}

_SUPPORTED_PROTOCOLS = frozenset({"http_connect", "socks5", "socks4", "socks4a"})

_HUNT_NOTEBOOK_PATHS = (
    Path(__file__).resolve().parents[2] / "var" / "port-araliklari" / "av-defteri.txt",
    Path(__file__).resolve().parents[2] / "config" / "hunt" / "av-defteri.txt",
)
_HUNT_NOTEBOOK = _HUNT_NOTEBOOK_PATHS[0]


def _read_hunt_notebook(path: Path | None = None) -> dict[str, Any]:
    """Operator hunt notebook: port/band scent that must be read on every decision."""
    if path:
        notebook = Path(path)
    else:
        notebook = next(
            (path for path in _HUNT_NOTEBOOK_PATHS if path.is_file()),
            _HUNT_NOTEBOOK_PATHS[0],
        )
    ports: list[int] = []
    bands: list[str] = []
    notes: list[str] = []
    try:
        lines = notebook.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"ports": ports, "bands": bands, "notes": notes, "path": str(notebook)}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            notes.append(line.lstrip("# ").strip())
            continue
        head, _, tail = line.partition(" ")
        head = head.strip().upper()
        tail = tail.strip()
        if head == "PORT":
            try:
                port = int(tail)
            except ValueError:
                continue
            if 1 <= port <= 65535 and port not in ports:
                ports.append(port)
        elif head == "BAND" and tail and tail not in bands:
            bands.append(tail)
    return {"ports": ports, "bands": bands, "notes": notes, "path": str(notebook)}


_CANONICAL_PORT_BANDS = (
    Path(__file__).resolve().parents[2] / "var" / "port-araliklari" / "yuksek.txt"
)
# Operator field notes (2026-09-09): real paid-proxy products rotate/sticky on
# vendor-specific ports; 3128 alone is the script-kiddie graveyard.
#   Oxylabs DC   rotate 8000  / sticky 8001-63000
#   Decodo DC    rotate 10000 / sticky 10001-63000
#   IPRoyal DC   rotate 12323 HTTP, 12324 SOCKS5
#   ProxyScrape  rotate 3129 HTTP, 1081 SOCKS5
#   Residential  7777 rotate; gateway variants 443, 7000, 823, 6060
# Sticky-IP products start at 10K and end at 63K.
_KLASIK_PORTLAR = (
    "80", "443", "823", "1080", "1081", "3128", "3129",
    "6060", "7000", "7777", "8000", "8001", "8080", "8118", "8888",
    "10000", "10001", "12323", "12324",
)
_URUN_PORT_BANTLARI = ("8001-63000", "10001-63000")
_AV_SOURCE_HOSTS = (
    "bgp.he.net",
    "myip.ms",
    "stat.ripe.net",
    "rdap.db.ripe.net",
    "rdap.arin.net",
    "rdap.apnic.net",
    "rdap.lacnic.net",
    "rdap.afrinic.net",
)
_AV_SOURCE_EXAMPLES = (
    "https://bgp.he.net/",
    "https://myip.ms/",
    "https://stat.ripe.net/data/whats-my-ip/data.json",
)
_OLU_HOST_SON = ("example.com", "example.net", "example.org", "whatismyip.com", "whatismyipaddress.com")

_PUBLIC_IPV4_RE = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")
_PUBLIC_CIDR_RE = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}/(?:[0-9]|[12][0-9]|3[0-2])(?![0-9])")
_PUBLIC_ASN_RE = re.compile(r"(?i)(?:\bASN\b|\bAS|aut-num[^0-9]{0,8})[^0-9]{0,4}([0-9]{1,10})")


def _public_source_facts(body: str) -> dict[str, list[Any]]:
    ips: set[str] = set()
    cidrs: set[str] = set()
    asns: set[int] = set()
    for raw in _PUBLIC_IPV4_RE.findall(body or ""):
        try:
            address = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if address.version == 4 and address.is_global:
            ips.add(str(address))
    for raw in _PUBLIC_CIDR_RE.findall(body or ""):
        try:
            network = ipaddress.ip_network(raw, strict=False)
        except ValueError:
            continue
        if network.version == 4 and network.is_global:
            cidrs.add(network.with_prefixlen)
    for raw in _PUBLIC_ASN_RE.findall(body or ""):
        try:
            asn = int(raw)
        except ValueError:
            continue
        if 1 <= asn <= 4294967295:
            asns.add(asn)
    return {
        "observed_ips": sorted(ips),
        "observed_cidrs": sorted(cidrs),
        "observed_asns": sorted(asns),
    }


def _hunt_notebook_hint() -> str:
    """Operator hunt notebook as prose, so the model actually uses the scent."""
    notebook = _read_hunt_notebook()
    ports = notebook.get("ports") or []
    bands = notebook.get("bands") or []
    if not ports and not bands:
        return ""
    port_text = ", ".join(str(port) for port in ports)
    band_text = ", ".join(str(band) for band in bands)
    return (
        f" Operatör av defteri: ürün-spesifik vekil portları [{port_text}]"
        + (f", sticky bantları [{band_text}]" if band_text else "")
        + ". 3128/1080 tek başına script-kiddie mezarlığıdır; ilk diş için bu "
        "ürün portlarını öncelikle düşün (1080/3128 son çare), canlı IP çıkınca "
        "port_scan_live_ip ile TÜM portlarını çıkar."
    )


def _hunter_instruction(observations: list[dict[str, Any]]) -> str:
    """Keep the AI moving from runtime preflight into real public-source hunting."""
    notebook_hint = _hunt_notebook_hint()
    runtime_seen = any(item.get("tool") == "observe_vds_surface" for item in observations)
    source_seen = any(
        item.get("tool") == "browse_public_source"
        and isinstance(item.get("result"), dict)
        and 200 <= int(item["result"].get("status", 0) or 0) < 400
        for item in observations
    )
    if source_seen:
        return (notebook_hint + 
            "Public av kaynağı kanıtı artık mevcut. observe_vds_surface tekrar seçme; "
            "kaynak gövdesindeki gözlenmiş IP/org/ASN sinyalinden inspect_owner_context "
            "veya list_owner_ranges seç, sonra gerekçeli ilk dişine geç. "
            "Genel DNS/bootstrap hedeflerini başlangıç kokusu sayma; "
            "masscan discovered boşsa port_scan_live_ip seçme. "
            "ÖNEMLİ: masscan canlı IP verdiyse o IP'yi ATMA. port_scan_live_ip ile "
            "TÜM açık portlarını tara; her açık port ayrı doğrulanır. Bir portun "
            "proxy vermemesi IP'yi öldürmez; diğer portları ayrı ayrı doğrula."
        )
    if runtime_seen:
        return (notebook_hint + 
            "VDS runtime yüzeyi zaten gözlendi; observe_vds_surface tekrar seçme. "
            "Şimdi browse_public_source ile yalnız av hostlarından birini seç: "
            "bgp.he.net, stat.ripe.net, rdap.* veya myip.ms. "
            "Genel web araması, örnek sayfalar veya DNS/bootstrap hedefleri kullanma; "
            "kaynak kanıtı olmadan CIDR/ASN/port uydurma."
        )
    return (
        notebook_hint
        + " İlk turda runtime yüzeyini en fazla bir kez gözle; sonra public-source koku araştırmasına geç."
    )


def _allowed_port_bands() -> list[str]:
    notebook = _read_hunt_notebook()
    return (
        list(_KLASIK_PORTLAR)
        + list(_URUN_PORT_BANTLARI)
        + [str(port) for port in notebook["ports"]]
        + list(notebook["bands"])
        + list(bant_listesi(_CANONICAL_PORT_BANDS))
    )


def _port_intervals(value: Any) -> list[tuple[int, int]]:
    values = value if isinstance(value, (list, tuple)) else str(value or "").replace(";", ",").split(",")
    intervals: list[tuple[int, int]] = []
    for item in values:
        text = str(item).strip()
        if not text:
            continue
        if "-" in text:
            left, right = text.split("-", 1)
            start = _validated_port(left, "port")
            end = _validated_port(right, "port")
            if start > end:
                raise ValueError("port aralığı ters")
            intervals.append((start, end))
        else:
            port = _validated_port(text, "port")
            intervals.append((port, port))
    if not intervals:
        raise ValueError("port niyeti boş olamaz")
    return intervals


def _validate_port_policy(value: Any) -> None:
    """Shape-only port validation.

    Port scope is the planner's decision. The hunt notebook and the high-band
    list stay available as scent/priority hints in the tool catalog, but they
    must never block a port set the planner chose.
    """
    _port_intervals(value)
def _validated_public_url(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} string olmalı")
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field} mutlak http/https URL olmalı")
    if parsed.username or parsed.password:
        raise ValueError(f"{field} kullanıcı bilgisi içeremez")
    return value


def _validated_port(value: Any, field: str = "port") -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} 1..65535 arasında olmalı")
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} 1..65535 arasında olmalı") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{field} 1..65535 arasında olmalı")
    return port


def _validated_port_intent(arguments: dict[str, Any]) -> tuple[str, Any]:
    for field in ("ports", "port_spec", "port_range"):
        if field not in arguments:
            continue
        value = arguments.get(field)
        items = list(value) if isinstance(value, (list, tuple)) else str(value or "").replace(";", ",").split(",")
        normalized: list[Any] = []
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            if "-" in text:
                left, right = text.split("-", 1)
                start = _validated_port(left, field)
                end = _validated_port(right, field)
                if start > end:
                    raise ValueError(f"{field} aralığı ters")
                normalized.append(f"{start}-{end}")
            else:
                normalized.append(_validated_port(text, field))
        if normalized:
            if field == "ports":
                return field, normalized
            return field, ",".join(str(item) for item in normalized)
    raise ValueError("port niyeti boş olamaz: ports veya port_spec/port_range gerekli")


def _validated_port_intent_or_default(
    arguments: dict[str, Any],
    default: str = "1-65535",
) -> tuple[str, Any]:
    """Port intent is the planner's choice; a full scan is the default.

    masscan_liveness must never be blocked because the planner omitted ports:
    no port argument means every port.
    """
    if any(field in arguments for field in ("ports", "port_spec", "port_range")):
        return _validated_port_intent(arguments)
    _port_intervals(default)
    return "port_spec", default


def _validated_host_or_ip(arguments: dict[str, Any], result: dict[str, Any]) -> None:
    ip_value = str(arguments.get("ip") or "").strip()
    host_value = str(arguments.get("host") or "").strip()
    if not ip_value and not host_value:
        raise ValueError("host veya ip gerekli")
    if ip_value:
        result["ip"] = str(ipaddress.ip_address(ip_value))
    if host_value:
        if any(character.isspace() for character in host_value):
            raise ValueError("host boşluk içeremez")
        lowered = host_value.lower().rstrip(".")
        if any(lowered == dead or lowered.endswith("." + dead) for dead in _OLU_HOST_SON):
            raise ValueError("dekoratif/genel örnek host kabul edilmez")
        result["host"] = host_value


def _validated_protocols(value: Any) -> list[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError("protocols boş olamaz")
    protocols = [str(item).strip().lower() for item in values if str(item).strip()]
    if not protocols or any(protocol not in _SUPPORTED_PROTOCOLS for protocol in protocols):
        raise ValueError("desteklenmeyen proxy protokolü")
    return list(dict.fromkeys(protocols))


def validate_tool_arguments(name: str, arguments: Any) -> dict[str, Any]:
    "Araç argümanlarını yalnız şekil/alan düzeyinde doğrular; hiçbir yan etki üretmez."
    if name not in ARGUMENT_CONTRACTS:
        raise ValueError(f"tool not registered: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments dict olmalı")
    result = dict(arguments)

    if name == "observe_vds_surface":
        return result

    if name == "browse_public_source":
        result["url"] = _validated_public_url(arguments.get("url"), "browse_public_source.url")
        if arguments.get("timeout") is not None:
            try:
                timeout = float(arguments["timeout"])
            except (TypeError, ValueError):
                raise ValueError("browse_public_source.timeout sayısal olmalı") from None
            if not 0 < timeout <= 60:
                raise ValueError("browse_public_source.timeout 0..60 arasında olmalı")
            result["timeout"] = timeout
        return result

    if name == "inspect_owner_context":
        raw_ip = str(arguments.get("ip") or "").strip()
        if not raw_ip:
            raise ValueError("inspect_owner_context.ip gerekli")
        result["ip"] = str(ipaddress.ip_address(raw_ip))
        return result

    if name == "list_owner_ranges":
        raw_asn = str(arguments.get("asn") or "").strip().upper().removeprefix("AS")
        try:
            asn = int(raw_asn)
        except ValueError:
            raise ValueError("list_owner_ranges.asn geçersiz") from None
        if not 1 <= asn <= 4294967295:
            raise ValueError("list_owner_ranges.asn aralık dışında")
        result["asn"] = asn
        return result

    if name == "port_scan_live_ip":
        raw_ip = str(arguments.get("ip") or "").strip()
        if not raw_ip:
            raise ValueError("port_scan_live_ip.ip gerekli")
        result["ip"] = str(ipaddress.ip_address(raw_ip))
        port_range = str(arguments.get("port_range") or "1-65535").strip() or "1-65535"
        intervals = _port_intervals(port_range)
        if not intervals:
            raise ValueError("port_scan_live_ip.port_range boş olamaz")
        result["port_range"] = port_range
        for field, low, high in (("timeout", 0.05, 10.0), ("concurrency", 1, 2048)):
            if arguments.get(field) is not None:
                try:
                    value = float(arguments[field]) if field == "timeout" else int(arguments[field])
                except (TypeError, ValueError):
                    raise ValueError(f"port_scan_live_ip.{field} sayısal olmalı") from None
                if field == "timeout":
                    value = max(low, min(high, value))
                elif field == "concurrency":
                    value = max(int(low), min(int(high), value))
                result[field] = value
        return result

    if name in {"masscan_liveness", "expand_live_ip"}:
        if name == "masscan_liveness":
            raw_cidr = str(arguments.get("cidr") or "").strip()
            if not raw_cidr:
                raise ValueError("masscan_liveness.cidr gerekli")
            network = ipaddress.ip_network(raw_cidr, strict=False)
            if network.version != 4 or not network.is_global:
                raise ValueError("masscan_liveness.cidr publicly routable IPv4 olmalı")
            result["cidr"] = network.with_prefixlen
        else:
            raw_ip = str(arguments.get("ip") or "").strip()
            if not raw_ip:
                raise ValueError("expand_live_ip.ip gerekli")
            result["ip"] = str(ipaddress.ip_address(raw_ip))
        if name == "masscan_liveness":
            field, ports = _validated_port_intent_or_default(arguments)
        else:
            field, ports = _validated_port_intent(arguments)
        result[field] = ports
        _validate_port_policy(ports)
        if arguments.get("rate") is not None:
            try:
                rate = int(arguments["rate"])
            except (TypeError, ValueError):
                raise ValueError("rate sayısal olmalı") from None
            if not 1 <= rate <= 1_000_000:
                raise ValueError("rate aralık dışında")
            result["rate"] = rate
        if arguments.get("timeout") is not None:
            try:
                timeout = float(arguments["timeout"])
            except (TypeError, ValueError):
                raise ValueError("timeout sayısal olmalı") from None
            timeout = max(0.05, min(10.0, timeout))
            result["timeout"] = timeout
        if arguments.get("concurrency") is not None:
            try:
                concurrency = int(arguments["concurrency"])
            except (TypeError, ValueError):
                raise ValueError("concurrency sayısal olmalı") from None
            concurrency = max(1, min(1024, concurrency))
            result["concurrency"] = concurrency
        return result

    if name == "validate_proxy":
        _validated_host_or_ip(arguments, result)
        result["port"] = _validated_port(arguments.get("port"))
        result["target_url"] = _validated_public_url(arguments.get("target_url"), "validate_proxy.target_url")
        result["protocols"] = _validated_protocols(arguments.get("protocols"))
        return result

    if name == "publish_proxy":
        validation_ref = str(arguments.get("validation_ref") or "").strip()
        if not validation_ref:
            raise ValueError("publish_proxy.validation_ref gerekli")
        result["validation_ref"] = validation_ref
        _validated_host_or_ip(arguments, result)
        result["port"] = _validated_port(arguments.get("port"))
        result["protocol"] = _validated_protocols(arguments.get("protocol"))[0]
        for field in ("quality_label", "quality_rationale"):
            value = str(arguments.get(field) or "").strip()
            if not value:
                raise ValueError(f"publish_proxy.{field} gerekli")
            result[field] = value
        return result

    raise ValueError(f"tool not registered: {name}")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    capabilities: tuple[str, ...]
    argument_contract: dict[str, Any]


class ToolCatalog:
    """Ajanın VDS'de gerçekten kullanabileceği dinamik araç kataloğu."""

    def __init__(self) -> None:
        self._handlers: dict[str, tuple[ToolSpec, Callable[[dict[str, Any]], dict[str, Any]]]] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: Callable[[dict[str, Any]], dict[str, Any]],
        capabilities: tuple[str, ...],
        argument_contract: dict[str, Any] | None = None,
    ) -> None:
        if name in self._handlers:
            raise ValueError(f"duplicate tool: {name}")
        contract = dict(argument_contract or ARGUMENT_CONTRACTS.get(name, {}))
        self._handlers[name] = (ToolSpec(name, description, capabilities, contract), handler)

    def describe(self) -> list[dict[str, Any]]:
        described: list[dict[str, Any]] = []
        for spec, _handler in self._handlers.values():
            item = {
                "name": spec.name,
                "description": spec.description,
                "capabilities": list(spec.capabilities),
                "arguments": dict(spec.argument_contract),
            }
            if spec.name in {"masscan_liveness", "expand_live_ip"}:
                item["allowed_port_source"] = "var/port-araliklari/yuksek.txt"
                item["allowed_port_ranges"] = _allowed_port_bands()
            if spec.name == "browse_public_source":
                item["allowed_hosts"] = list(_AV_SOURCE_HOSTS)
                item["source_examples"] = list(_AV_SOURCE_EXAMPLES)
            described.append(item)
        return described

    def invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        item = self._handlers.get(name)
        if item is None:
            raise KeyError(f"AI bilinmeyen araç seçti: {name}")
        return item[1](dict(arguments or {}))


class AgentRuntime:
    def __init__(
        self,
        *,
        root: Path,
        agent_id: str,
        job_id: str,
        kind: str,
        initial_input: str,
        emit: Callable[..., None],
        stopped: Callable[[], bool],
    ) -> None:
        self.root = Path(root).resolve()
        self.repo_root = Path(__file__).resolve().parents[2]
        self.agent_id = agent_id
        self.job_id = job_id
        self.kind = kind
        self.initial_input = str(initial_input or "").strip()
        self.emit = emit
        self.stopped = stopped
        self.agent_dir = self.root / "agents" / agent_id
        self.output_dir = self.agent_dir / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.catalog = ToolCatalog()
        self.observations: list[dict[str, Any]] = []
        self.last_decision: dict[str, Any] = {}
        self.last_tool_result: dict[str, Any] = {}
        self._directive_offset = 0
        self.operator_directives: list[dict[str, Any]] = []
        self.step = 0
        self._open_ports_to_validate: list[dict[str, Any]] = []
        self._validated_ports: set[tuple[str, int]] = set()
        self._open_ports_by_host: dict[str, set[int]] = {}
        self._fact_store: dict[str, set[Any]] = self._load_fact_store()
        self._load_open_port_state()
        self._outcome_records: list[dict[str, Any]] = self._load_recent_outcomes()
        self._decision_phase = "hunt"
        self._runtime_preflight_done = False
        self._source_decision_attempts = 0
        self._source_successes = 0
        self._intent_decision_attempts = 0
        self._source_decision_budget = 3
        self._intent_decision_budget = 4
        self._register_tools()
        self._load_portscan_evidence()

    def _register_tools(self) -> None:
        self.catalog.register(
            "observe_vds_surface",
            "VDS işletim sistemi, araçlar, disk, çalışma alanı ve mevcut kanıt dosyalarını gözlemler.",
            self._observe_vds_surface,
            ("read_only", "runtime"),
        )
        self.catalog.register(
            "browse_public_source",
            "AI'nin seçtiği herkese açık HTTP(S) kaynağını VDS'den okur; gövde hash'i ve sınırlı içerik özeti saklar.",
            self._browse_public_source,
            ("read_only", "internet"),
        )
        self.catalog.register(
            "inspect_owner_context",
            "Verilen IP için RDAP sahiplik, ağ aralığı ve ASN bağlamını VDS'den sorgular.",
            self._inspect_owner_context,
            ("read_only", "rdap"),
        )
        self.catalog.register(
            "list_owner_ranges",
            "Bir ASN için herkese açık duyurulan kardeş IPv4 aralıklarını VDS'den okur.",
            self._list_owner_ranges,
            ("read_only", "routing"),
        )
        self.catalog.register(
            "masscan_liveness",
            "AI'nin seçtiği CIDR/port niyetini VDS'de Masscan ile yalnız L4 canlılık için çalıştırır.",
            self._masscan_liveness,
            ("network", "l4", "masscan"),
        )
        self.catalog.register(
            "port_scan_live_ip",
            "Canlı IP'de TÜM açık portları tarar (gerçek port scanner); her açık port L7'de doğrulanır.",
            self._port_scan_live_ip,
            ("network", "socket", "portscan"),
        )
        self.catalog.register(
            "expand_live_ip",
            "Masscan sonrası tek canlı IP'nin seçilmiş portlarını doğrudan socket ile dikey genişletir; Masscan çağırmaz.",
            self._expand_live_ip,
            ("network", "socket", "vertical"),
        )
        self.catalog.register(
            "validate_proxy",
            "Açık uçta AI'nin seçtiği protokollerle el sıkışır ve gerçek HTTP hedefi üzerinden çıkış kanıtı arar.",
            self._validate_proxy,
            ("network", "l7", "egress"),
        )
        self.catalog.register(
            "publish_proxy",
            "Önceden doğrulanmış kanıt referansını teslim kuyruğuna yazar; doğrulanmamış uç kabul etmez.",
            self._publish_proxy,
            ("write", "delivery"),
        )

    @staticmethod
    def _port_key(item: dict[str, Any]) -> tuple[str, int]:
        return (str(item.get("host") or item.get("ip") or ""), int(item.get("port") or 0))

    def _register_open_ports(self, host: str, ports: list[int]) -> int:
        """Register open ports as work that must be validated.

        An open port simply is a port that has to go to L7. Registration only
        de-duplicates work.
        """
        added = 0
        existing = {self._port_key(item) for item in self._open_ports_to_validate}
        host = str(host or "")
        for raw_port in ports:
            try:
                port = int(raw_port)
            except (TypeError, ValueError):
                continue
            key = (host, port)
            if not key[0] or not 1 <= key[1] <= 65535:
                continue
            self._open_ports_by_host.setdefault(host, set()).add(port)
            if key in existing or key in self._validated_ports:
                continue
            existing.add(key)
            self._open_ports_to_validate.append({"host": host, "port": port})
            added += 1
        if added:
            self._persist_open_port_state()
        return added

    def _open_port_state_path(self) -> Path:
        return self.agent_dir / "open-port-state.json"

    def _load_open_port_state(self) -> None:
        """Restart-safe open-port/validated-port state.

        Without this, a worker restart forgets which real open ports still
        need L7 and the observer sees them as dropped coverage.
        """
        path = self._open_port_state_path()
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        registry = payload.get("open_ports_by_host") or {}
        if isinstance(registry, dict):
            for host, ports in registry.items():
                for raw_port in ports or []:
                    try:
                        port = int(raw_port)
                    except (TypeError, ValueError):
                        continue
                    if 1 <= port <= 65535:
                        self._open_ports_by_host.setdefault(str(host), set()).add(port)
        for item in payload.get("validated_ports") or []:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                try:
                    self._validated_ports.add((str(item[0]), int(item[1])))
                except (TypeError, ValueError):
                    continue
        self._open_ports_to_validate = [
            {"host": host, "port": port}
            for host, ports in self._open_ports_by_host.items()
            for port in sorted(ports)
            if (host, port) not in self._validated_ports
        ]

    def _persist_open_port_state(self) -> None:
        payload = {
            "open_ports_by_host": {
                host: sorted(ports)
                for host, ports in sorted(self._open_ports_by_host.items())
            },
            "validated_ports": sorted(
                [host, port] for host, port in self._validated_ports
            ),
        }
        _json_write(self._open_port_state_path(), payload)

    @staticmethod
    def _step_from_output_name(name: str) -> int:
        match = re.search(r"-(\d{3,})\.(?:json|jsonl)$", name)
        return int(match.group(1)) if match else -1

    def _load_portscan_evidence(self) -> None:
        """Re-process real port-scan artifacts on startup.

        Old scans must not be orphaned by a restart: their socket-confirmed
        open ports are registered as pending L7 work and their IPs become real
        target evidence.
        """
        newest: dict[str, tuple[tuple[int, float], dict[str, Any]]] = {}
        for pattern in ("portscan-*.json", "vertical-*.json"):
            for path in self.output_dir.glob(pattern):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                ip = str(payload.get("ip") or "")
                open_ports = payload.get("open_ports") or []
                if not ip or not isinstance(open_ports, list) or not open_ports:
                    continue
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                key = (self._step_from_output_name(path.name), mtime)
                current = newest.get(ip)
                if current is None or key > current[0]:
                    newest[ip] = (key, payload)
        for ip, (_key, payload) in newest.items():
            self._add_fact_ip(self._fact_store, ip, "live_ips")
            self._add_fact_ip(self._fact_store, ip, "source_ips")
            ports = [
                int(port)
                for port in (payload.get("open_ports") or [])
                if str(port).isdigit()
            ]
            self._register_open_ports(ip, ports)
        self._persist_fact_store()
        self._persist_open_port_state()

    def _unvalidated_open_ports(
        self,
        sample: int = 20,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Per-IP coverage gap: found open ports minus real L7 attempts."""
        report: list[dict[str, Any]] = []
        for host, ports in self._open_ports_by_host.items():
            missing = sorted(
                port for port in ports if (host, port) not in self._validated_ports
            )
            if not missing:
                continue
            report.append({
                "ip": host,
                "open_ports": len(ports),
                "validated": len(ports) - len(missing),
                "missing_count": len(missing),
                "missing_sample": missing[:sample],
            })
        report.sort(key=lambda item: item["missing_count"], reverse=True)
        return report[:limit]

    def _pending_open_ports(self) -> list[dict[str, Any]]:
        return [
            dict(item)
            for item in self._open_ports_to_validate
            if self._port_key(item) not in self._validated_ports
        ]

    def _mark_port_validated(self, item: dict[str, Any]) -> None:
        key = self._port_key(item)
        self._validated_ports.add(key)
        self._open_ports_to_validate = [
            entry for entry in self._open_ports_to_validate if self._port_key(entry) != key
        ]

    def _validate_port_direct(
        self,
        host: str,
        port: int,
        target_url: str,
        protocols: list[str],
    ) -> dict[str, Any]:
        """Validate one open port without going through the planner."""
        return self._validate_proxy({
            "host": host,
            "port": port,
            "target_url": target_url,
            "protocols": protocols,
        })

    @staticmethod
    def _l7_concurrency() -> int:
        try:
            value = int(os.environ.get("PAIDPROXY_L7_CONCURRENCY", "32") or "32")
        except ValueError:
            value = 32
        return max(1, min(1024, value))

    def _validate_open_ports(
        self,
        host: str,
        ports: list[int],
        target_url: str = "https://httpbin.org/ip",
        protocols: tuple[str, ...] = ("http_connect", "socks5", "socks4", "socks4a"),
    ) -> dict[str, Any]:
        """Validate every open port with bounded concurrency.

        No queue cut, no per-turn discretion: every open port on the host is
        probed, each result is written to JSONL, progress is emitted every 100
        ports, and the operator stop signal ends the run.
        """
        unique_ports: list[int] = []
        seen: set[int] = set()
        for raw_port in ports:
            try:
                port = int(raw_port)
            except (TypeError, ValueError):
                continue
            if 1 <= port <= 65535 and port not in seen:
                seen.add(port)
                unique_ports.append(port)
        unique_ports.sort()
        total = len(unique_ports)
        already_validated = sum(
            1 for port in unique_ports if (str(host), port) in self._validated_ports
        )
        pending = [
            port for port in unique_ports if (str(host), port) not in self._validated_ports
        ]
        results_path = self.output_dir / f"l7-open-ports-{self.step:05d}.jsonl"
        checked = 0
        egress_hits: list[dict[str, Any]] = []
        stopped = False

        def work(port: int) -> tuple[int, dict[str, Any]]:
            if self.stopped():
                return port, {"results": [], "validated": [], "error": "operator_stop"}
            try:
                result = self._validate_port_direct(host, port, target_url, list(protocols))
            except Exception as exc:  # one dead port must not kill the run
                result = {
                    "results": [],
                    "validated": [],
                    "error": f"{type(exc).__name__}: {exc}",
                }
            return port, result

        if pending and not self.stopped():
            workers = min(self._l7_concurrency(), len(pending))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(work, port): port for port in pending}
                for future in as_completed(futures):
                    if self.stopped():
                        stopped = True
                        for pending_future in futures:
                            pending_future.cancel()
                        break
                    port, result = future.result()
                    checked += 1
                    confirmed = any(
                        item.get("egress_confirmed")
                        for item in (result.get("results") or [])
                        if isinstance(item, dict)
                    ) or any(
                        item.get("egress_confirmed")
                        for item in (result.get("validated") or [])
                        if isinstance(item, dict)
                    )
                    _append_jsonl(results_path, {
                        "host": host,
                        "port": port,
                        "egress_confirmed": bool(confirmed),
                        "validated_count": len(result.get("validated") or []),
                        "error": result.get("error"),
                    })
                    if confirmed:
                        egress_hits.append({"host": host, "port": port})
                    self._mark_port_validated({"host": host, "port": port})
                    if checked % 100 == 0:
                        self.emit(
                            "l7_progress",
                            f"Açık port doğrulama ilerlemesi: {checked}/{len(pending)}.",
                            state="running",
                            tool="validate_proxy",
                            target=f"vds://agent/l7/{host}",
                            checked=checked,
                            total=len(pending),
                            egress_hits=len(egress_hits),
                            next_action="kalan açık portlar doğrulanıyor",
                        )
        if checked:
            self._persist_open_port_state()
        return {
            "checked": checked,
            "total": total,
            "already_validated": already_validated,
            "pending": sum(
                1
                for port in unique_ports
                if (str(host), port) not in self._validated_ports
            ),
            "egress_hits": egress_hits,
            "stopped": stopped,
            "results_ref": f"agent://{self.agent_id}/{results_path.relative_to(self.agent_dir)}",
        }

    def _priority_hunt_ports(self) -> list[int]:
        """Operator product ports first, legacy script-kiddie ports last.

        The model repeatedly chose 1080/3128 even with the notebook in front of
        it, so priority is enforced deterministically instead of suggested.
        """
        notebook = self._hunt_notebook()
        operator_ports = [int(port) for port in (notebook.get("ports") or [])]
        legacy = [1080, 3128, 8080, 8888, 8118, 80, 443]
        ordered: list[int] = []
        for port in operator_ports + legacy:
            if port not in ordered:
                ordered.append(port)
        return ordered

    def _hunt_notebook(self) -> dict[str, Any]:
        return _read_hunt_notebook()

    def _available_tools_for_phase(self) -> list[dict[str, Any]]:
        tools = list(self.catalog.describe())
        if self._runtime_preflight_done:
            tools = [tool for tool in tools if tool.get("name") != "observe_vds_surface"]
        return tools

    def run(self) -> int:
        self.emit(
            "tool_catalog",
            "VDS araç kataloğu AI kararına açıldı.",
            state="running",
            tool="tool_catalog",
            target="vds://agent/tools",
            evidence_refs=[f"agent://{self.agent_id}/tool-catalog.json"],
            next_action="AI ilk gözlemi seçecek",
            tool_count=len(self.catalog.describe()),
        )
        _json_write(self.output_dir / "tool-catalog.json", self.catalog.describe())
        if self.stopped():
            return 130
        runtime_context = self._observe_vds_surface({})
        self._runtime_preflight_done = True
        context_ref = _json_write(self.output_dir / "runtime-context.json", runtime_context)
        self.observations.append({"tool": "runtime_context", "result": runtime_context, "at": _utc()})
        self.last_tool_result = dict(runtime_context)
        self.emit(
            "runtime_context",
            "VDS runtime bağlamı AI kararından önce salt okunur olarak hazırlandı; operasyon aracı zorlanmadı.",
            state="running",
            tool="runtime_context",
            target="vds://agent/runtime",
            evidence_refs=[context_ref],
            output_ref=context_ref,
            next_action="AI ilk operasyonel adımı seçecek",
        )
        idle_rounds = 0
        consecutive_no_tool_rounds = 0
        while not self.stopped():
            self._read_operator_directives()
            self.step += 1
            decision = self._decide()
            if decision is None:
                idle_rounds += 1
                if idle_rounds >= 3:
                    fallback_decision = self._autonomous_hunt_decision()
                    if fallback_decision:
                        self.emit(
                            "autonomous_fallback_engaged",
                            "AI sağlayıcısından geçerli araç kararı gelmedi; avın durmaması için deterministik avcı kararı devrede.",
                            tool="autonomous_hunter",
                            target="vds://agent/fallback",
                            decision=fallback_decision.get("action"),
                            hypothesis=self._text(fallback_decision.get("expected_value")),
                            counter_hypothesis=self._first(fallback_decision.get("counter_evidence")),
                            next_action="Deterministik araç yürütülecek",
                            idle_rounds=idle_rounds,
                        )
                        decision = fallback_decision
                if decision is None:
                    self.emit(
                        "reflection_waiting",
                        "AI sağlayıcısından geçerli araç kararı gelmedi; sahte ilerleme üretmeden yeniden gözlem bekleniyor.",
                        tool="ai_planner",
                        target="vds://agent/decision",
                        next_action="AI yeniden değerlendirilecek",
                        idle_rounds=idle_rounds,
                    )
                    time.sleep(min(15.0, 2.0 + idle_rounds))
                    continue
            idle_rounds = 0
            tools = self._requested_tools(decision)
            if not tools:
                consecutive_no_tool_rounds += 1
                if consecutive_no_tool_rounds >= 3:
                    fallback_decision = self._autonomous_hunt_decision()
                    if fallback_decision:
                        fallback_tools = self._requested_tools(fallback_decision)
                        if fallback_tools:
                            tools = fallback_tools
                            decision = fallback_decision
                            consecutive_no_tool_rounds = 0
                if not tools:
                    self.emit(
                        "decision_waiting",
                        "AI bu turda araç seçmedi; gerekçe ve karşı kanıt görünür biçimde saklandı.",
                        tool="ai_planner",
                        target="vds://agent/decision",
                        hypothesis=self._text(decision.get("expected_value")),
                        counter_hypothesis=self._first(decision.get("counter_evidence")),
                        evidence_refs=self._decision_evidence(decision),
                        decision=decision.get("action"),
                        next_action="Yeni gözlem veya AI araç kararı",
                    )
                    time.sleep(5.0)
                    continue
            consecutive_no_tool_rounds = 0
            for tool_name, arguments in tools:
                if self.stopped():
                    break
                self._invoke(tool_name, arguments)
        self.emit(
            "agent_stopping",
            "AI runtime operatör sinyaliyle durdu.",
            state="stopping",
            tool="agent_runtime",
            target="vds://agent",
            operator_action="stop",
            next_action="worker exit",
        )
        return 130

    def _autonomous_hunt_decision(self) -> dict[str, Any] | None:
        """Deterministic fallback when AI planner repeatedly fails or is unavailable.

        Ensures the agent makes real forward progress with validate_proxy,
        port_scan_live_ip, or masscan_liveness instead of remaining stuck.
        """
        # 1. Unvalidated open ports from pending list
        pending = self._pending_open_ports()
        if pending:
            item = pending[0]
            host = str(item.get("host") or item.get("ip") or "").strip()
            port = int(item.get("port") or 0)
            if host and port > 0:
                protocols = list(item.get("protocols") or ["http_connect", "socks5", "socks4"])
                target_url = str(item.get("target_url") or "https://httpbin.org/ip")
                return {
                    "action": "deep_test",
                    "requested_tools": ["validate_proxy"],
                    "resource_plan": {
                        "tool_arguments": {
                            "validate_proxy": {
                                "host": host,
                                "port": port,
                                "target_url": target_url,
                                "protocols": protocols,
                            }
                        }
                    },
                    "expected_value": f"Deterministik otonom: {host}:{port} açık portu L7 için doğrulanıyor.",
                    "counter_evidence": ["AI planlayıcı yanıt vermedi; deterministik avcı kuralı devreye girdi."],
                    "provider": "autonomous-hunter",
                    "model": "deterministic-v1",
                }

        # 2. Coverage gaps: found open ports without L7 proof
        unvalidated = self._unvalidated_open_ports()
        if unvalidated:
            ip = str(unvalidated[0].get("ip") or "").strip()
            if ip:
                return {
                    "action": "expand",
                    "requested_tools": ["port_scan_live_ip"],
                    "resource_plan": {
                        "tool_arguments": {
                            "port_scan_live_ip": {
                                "ip": ip,
                                "port_range": "1-65535",
                            }
                        }
                    },
                    "expected_value": f"Deterministik otonom: {ip} canlı IP eksik portları taranıyor.",
                    "counter_evidence": ["AI planlayıcı yanıt vermedi; canlı IP port taraması sürdürülüyor."],
                    "provider": "autonomous-hunter",
                    "model": "deterministic-v1",
                }

        # 3. Live IPs not yet port-scanned
        live_ips = sorted(self._fact_store.get("live_ips") or set())
        for ip in live_ips:
            ip_str = str(ip).strip()
            if ip_str and ip_str not in self._open_ports_by_host:
                return {
                    "action": "expand",
                    "requested_tools": ["port_scan_live_ip"],
                    "resource_plan": {
                        "tool_arguments": {
                            "port_scan_live_ip": {
                                "ip": ip_str,
                                "port_range": "1-65535",
                            }
                        }
                    },
                    "expected_value": f"Deterministik otonom: Taranmamış canlı IP {ip_str} için port taraması başlatılıyor.",
                    "counter_evidence": ["AI planlayıcı yanıt vermedi; taranmamış canlı IP taranıyor."],
                    "provider": "autonomous-hunter",
                    "model": "deterministic-v1",
                }

        # 4. CIDR liveness scan
        cidrs = sorted(self._fact_store.get("cidrs") or set())
        if cidrs:
            target_cidr = cidrs[0]
            ports = self._priority_hunt_ports()
            return {
                "action": "sample",
                "requested_tools": ["masscan_liveness"],
                "resource_plan": {
                    "tool_arguments": {
                        "masscan_liveness": {
                            "cidr": str(target_cidr),
                            "ports": ports[:12],
                            "rate": 5000,
                        }
                    }
                },
                "expected_value": f"Deterministik otonom: {target_cidr} CIDR için ürün portlarında canlılık taranıyor.",
                "counter_evidence": ["AI planlayıcı yanıt vermedi; bilinen CIDR havuzunda canlılık aranıyor."],
                "provider": "autonomous-hunter",
                "model": "deterministic-v1",
            }

        # 5. Public source research
        return {
            "action": "research",
            "requested_tools": ["browse_public_source"],
            "resource_plan": {
                "tool_arguments": {
                    "browse_public_source": {
                        "url": "https://myip.ms/",
                    }
                }
            },
            "expected_value": "Deterministik otonom: Yeni vekil kokusu için myip.ms taranıyor.",
            "counter_evidence": ["AI planlayıcı yanıt vermedi; kamuya açık kaynak taranıyor."],
            "provider": "autonomous-hunter",
            "model": "deterministic-v1",
        }

    def _planner_snapshot(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "job_id": self.job_id,
            "agent_kind": self.kind,
            "initial_input": self.initial_input,
            "step": self.step,
            "decision_phase": self._decision_phase,
            "available_tools": self._available_tools_for_phase(),
            "observations": self.observations[-12:],
            "last_tool_result": self.last_tool_result,
            "operator_directives": self.operator_directives[-20:],
            "operator_hunt_notebook": self._hunt_notebook(),
            "open_ports_to_validate": self._pending_open_ports()[:80],
            "unvalidated_open_ports": self._unvalidated_open_ports(),
            "priority_hunt_ports": self._priority_hunt_ports(),
            "recent_outcomes": self._outcome_records[-12:],
            "durable_evidence": self._evidence_summary(),
            "previous_decision": {
                "action": self.last_decision.get("action"),
                "expected_value": self.last_decision.get("expected_value"),
                "counter_evidence": self.last_decision.get("counter_evidence", []),
            },
            "instruction": (
                "Bir sonraki adımı sen seç. requested_tools alanına yalnız katalogdaki "
                "araç adlarını yaz; resource_plan.tool_arguments içinde her araç için argüman "
                "nesnesi ver. Her requested_tools öğesinin resource_plan.tool_arguments değeri, "
                "available_tools içindeki arguments kontratını eksiksiz karşılamalıdır. "
                "browse_public_source.url mutlak http:// veya https:// URL olmalı ve katalogdaki source_examples/allowed_hosts içinden seçilmelidir. "
                "Kontratı karşılayamıyorsan aracı isteme. Kanıt ve karşı kanıtı ayır. "
                "L4 canlılık ile L7 gerçek-site "
                "çıkışını karıştırma. Masscan yalnız ilk canlılık içindir; canlı IP'de "
                "dikey genişleme için expand_live_ip socket aracını seç. "
                "Masscan bir canlı IP verdiyse port_scan_live_ip ile o IP'nin TÜM "
                "açık portlarını çıkar; her açık port tek tek "
                "validate_proxy edilir. Bir port ölü diye IP'yi bırakma. "
                "Sabit skor üretme. Açık portlar taranır taranmaz mekanik "
                "doğrulamaya gider; snapshot.open_ports_to_validate BOŞ DEĞİLSE "
                "kalanları validate_proxy ile bitir ve boşalana kadar yeni "
                "hedefe geçme. snapshot.unvalidated_open_ports bir IP için "
                "missing_count > 0 gösteriyorsa o IP'nin port_scan_live_ip veya "
                "expand_live_ip çağrısıyla eksik portlarını kapat; hiçbir açık "
                "portu doğrulanmadan bırakma. "
                "Gerçek bir HTTP(S) hedefini target_url alanında kendin seçmeden L7 doğrulama "
                "isteme. validate_proxy için protocols alanında hangi protokolleri deneyeceğini "
                "açıkça seç; protokol listesi eksikse araç çağrısı yapma. publish_proxy için "
                "validation_ref, host, port, protocol, quality_label ve quality_rationale "
                "alanlarını kanıtla. "
                "Avcısın: sahiplik ve kardeş aralıkla kokla; örnek sayfa, genel web araması "
                "ve DNS/bootstrap hedefi ölü zemindir. Koku yoksa ısırma. İlk dişi, port "
                "kümesini ve taranacak aralıkları sen seç; sağlayıcının bütün aralıkları "
                "hedef olabilir. Kan varsa aynı dişle komşu, dağı yutma. "
                "snapshot.recent_outcomes ve snapshot.durable_evidence gerçek araç "
                "sonuçlarıdır; aynı cümleyi tekrarlamak yerine onlarla karar ver. "
                "Çıkışsız açık port vekil değil."
            ) + " " + _hunter_instruction(self.observations),
        }

    def _decide(self) -> dict[str, Any] | None:
        snapshot = self._planner_snapshot()
        try:
            raw = claude_planner_decide(snapshot)
        except Exception as exc:
            self.emit(
                "ai_unavailable",
                f"Claude Code planner kararı alınamadı: {type(exc).__name__}.",
                state="waiting",
                tool="claude_planner",
                target="vds://agent/decision",
                error=f"{type(exc).__name__}: {exc}",
                next_action="ayrı LLM tamir katmanı devreye girecek; sahte karar üretilmedi",
            )
            return None
        decision = dict(raw or {})
        self.last_decision = decision
        evidence_ref = _json_write(self.output_dir / f"decision-{self.step:05d}.json", decision)
        self.emit(
            "decision_made",
            self._text(decision.get("expected_value")) or "AI araç kararı hazır.",
            tool="ai_planner",
            target="vds://agent/decision",
            hypothesis=self._first(decision.get("evidence")),
            counter_hypothesis=self._first(decision.get("counter_evidence")),
            evidence_refs=[evidence_ref],
            decision={
                "action": decision.get("action"),
                "requested_tools": decision.get("requested_tools", []),
                "targets": decision.get("targets", []),
                "provider": decision.get("provider"),
                "model": decision.get("model"),
            },
            next_action="AI seçtiği araçlar yürütülecek",
        )
        return decision

    @staticmethod
    def _flat_tool_arguments(decision: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """Accept the planner's flat {"tool_arguments": {name: args}} shape.

        The model sometimes drops requested_tools/resource_plan and returns the
        arguments directly, or a list of argument objects for one tool. That is
        still a real, executable intent; silently waiting forever is a bug.
        """
        flat = decision.get("tool_arguments")
        if not isinstance(flat, dict):
            return []
        expanded: list[tuple[str, dict[str, Any]]] = []
        for raw_name, value in flat.items():
            name = str(raw_name or "").strip()
            if not name:
                continue
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        expanded.append((name, dict(item)))
            elif isinstance(value, dict):
                expanded.append((name, dict(value)))
        return expanded

    def _requested_tools(self, decision: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        names = decision.get("requested_tools") or []
        if isinstance(names, str):
            names = [names]
        if not names:
            # Keep one dict per occurrence so repeated tools (e.g. validating a
            # list of live IPs) each carry their own arguments.
            names = [
                {"name": name, "tool_arguments": arguments}
                for name, arguments in self._flat_tool_arguments(decision)
            ]
        if not names:
            # Shape seen in the wild: resource_plan.tool + nested
            # resource_plan.tool_arguments{name: args} without requested_tools.
            plan = decision.get("resource_plan")
            if isinstance(plan, dict):
                single = str(plan.get("tool") or plan.get("name") or "").strip()
                nested = plan.get("tool_arguments")
                if single and isinstance(nested, dict):
                    inner = nested.get(single)
                    if isinstance(inner, dict):
                        names = [{"name": single, "tool_arguments": dict(inner)}]
                    else:
                        names = [{"name": single, "tool_arguments": dict(nested)}]
        resource_plan = decision.get("resource_plan") or {}
        args_by_tool = resource_plan.get("tool_arguments", {}) if isinstance(resource_plan, dict) else {}
        if not isinstance(args_by_tool, dict):
            args_by_tool = {}

        result: list[tuple[str, dict[str, Any]]] = []
        errors: list[str] = []
        provenance_deferred: list[str] = []
        browse_requested = any(
            isinstance(entry, str) and entry == "browse_public_source"
            or isinstance(entry, dict)
            and str(entry.get("name") or entry.get("tool") or "").strip() == "browse_public_source"
            for entry in names
        )
        for raw_name in names:
            inline_arguments: Any = None
            if isinstance(raw_name, dict):
                name = str(
                    raw_name.get("name")
                    or raw_name.get("tool")
                    or raw_name.get("tool_name")
                    or ""
                ).strip()
                inline_plan = raw_name.get("resource_plan")
                if isinstance(inline_plan, dict):
                    inline_arguments = inline_plan.get("tool_arguments")
                if not isinstance(inline_arguments, dict):
                    inline_arguments = raw_name.get("tool_arguments")
                if not isinstance(inline_arguments, dict):
                    inline_arguments = raw_name.get("arguments")
                if isinstance(inline_arguments, dict) and name in inline_arguments:
                    nested_arguments = inline_arguments.get(name)
                    if isinstance(nested_arguments, dict):
                        inline_arguments = nested_arguments
            else:
                name = str(raw_name).strip()
            if name not in CONTROLLED_TOOLS or name not in ARGUMENT_CONTRACTS:
                errors.append(f"{name or '<empty>'}: tool not registered")
                continue
            arguments = inline_arguments if isinstance(inline_arguments, dict) else args_by_tool.get(name)
            if not isinstance(arguments, dict):
                errors.append(f"{name}: arguments dict gerekli")
                continue
            arguments = dict(arguments)
            aliases = {
                "one first port in ports or port_spec/port_range": "ports",
                "ports or port_spec/port_range": "ports",
                "port_spec/port_range": "port_spec",
            }
            for raw_key, value in list(arguments.items()):
                normalized_key = re.sub(r"\s+", " ", str(raw_key).strip()).lower()
                canonical_key = aliases.get(normalized_key)
                if canonical_key and canonical_key not in arguments:
                    arguments[canonical_key] = value
                if canonical_key and raw_key != canonical_key:
                    arguments.pop(raw_key, None)
                if normalized_key == "host or ip" and "host" not in arguments and "ip" not in arguments:
                    try:
                        ipaddress.ip_address(str(value).strip())
                    except ValueError:
                        arguments["host"] = value
                    else:
                        arguments["ip"] = value
                    arguments.pop(raw_key, None)
            try:
                normalized = validate_tool_arguments(name, arguments)
            except (TypeError, ValueError) as exc:
                if browse_requested and name != "browse_public_source":
                    provenance_deferred.append(f"{name}: kaynak kokusu gelmeden hedef zarfı atlandı")
                    continue
                errors.append(f"{name}: {str(exc)[:300]}")
                continue
            provenance_error = self._target_provenance_error(name, normalized)
            if provenance_error:
                if browse_requested:
                    provenance_deferred.append(f"{name}: {provenance_error}")
                    continue
                errors.append(f"{name}: {provenance_error}")
                continue
            result.append((name, normalized))

        if errors:
            self._reject_decision_contract(decision, "; ".join(errors)[:1200], errors)
            return []
        if provenance_deferred:
            self.emit(
                "tool_deferred",
                "Hedef aracı gerçek public-source veya probe kanıtı gelene kadar ertelendi.",
                state="waiting",
                tool="hunt_guard",
                target="vds://agent/provenance",
                deferred_tools=provenance_deferred,
                next_action="public-source veya gerçek canlılık kanıtı bekleniyor",
            )
        return result

    def _reject_decision_contract(
        self,
        decision: dict[str, Any],
        reason: str,
        rejected_tools: list[str] | None = None,
    ) -> None:
        rejection = {
            "error": reason,
            "event_type": "decision_contract_rejected",
            "tool": "tool_catalog",
            "rejected_tools": list(rejected_tools or []),
            "at": _utc(),
        }
        self.last_tool_result = rejection
        self.observations.append({"tool": "tool_catalog", "result": rejection, "at": _utc()})
        self.observations = self.observations[-100:]
        self.emit(
            "decision_contract_rejected",
            "AI kararının araç argüman sözleşmesi reddedildi.",
            state="waiting",
            tool="ai_planner",
            target="vds://agent/decision",
            error=reason,
            decision=decision.get("action"),
            rejected_tools=list(rejected_tools or []),
            next_action="AI katalog argüman sözleşmesine göre yeniden karar verecek",
        )

    def _latest_public_source_evidence(self) -> list[str]:
        for observation in reversed(self.observations):
            if observation.get("tool") != "browse_public_source":
                continue
            result = observation.get("result")
            if not isinstance(result, dict):
                continue
            try:
                url = _validated_public_url(result.get("url"), "browse_public_source.url")
                status = int(result.get("status", 0))
            except (TypeError, ValueError):
                continue
            refs = [str(ref) for ref in result.get("evidence_refs", []) if str(ref).strip()]
            if url and 200 <= status < 400 and refs:
                return refs
        return []

    @staticmethod
    def _decision_cites_source(decision: dict[str, Any], source_refs: list[str]) -> bool:
        evidence = {
            str(item).strip()
            for item in (decision.get("evidence") or [])
            if str(item).strip()
        }
        return bool(evidence.intersection(source_refs))

    @staticmethod
    def _add_fact_ip(facts: dict[str, set[Any]], value: Any, bucket: str = "ips") -> None:
        try:
            address = ipaddress.ip_address(str(value).strip())
        except ValueError:
            return
        if address.version == 4 and address.is_global:
            facts[bucket].add(str(address))
            facts["ips"].add(str(address))

    @staticmethod
    def _add_fact_asn(facts: dict[str, set[Any]], value: Any) -> None:
        try:
            asn = int(str(value).strip().upper().removeprefix("AS"))
        except (TypeError, ValueError):
            return
        if 1 <= asn <= 4294967295:
            facts["asns"].add(asn)

    @staticmethod
    def _add_fact_cidr(facts: dict[str, set[Any]], value: Any) -> None:
        try:
            network = ipaddress.ip_network(str(value).strip(), strict=False)
        except ValueError:
            return
        if network.version == 4 and network.is_global:
            facts["cidrs"].add(network)

    def _merge_observation_facts(
        self,
        facts: dict[str, set[Any]],
        observation: dict[str, Any],
    ) -> None:
        """Merge every real source/probe result into a fact set.

        This is the single parser used both for the durable fact store and for
        a fresh scan of the observation window.
        """
        tool = observation.get("tool")
        result = observation.get("result")
        if not isinstance(result, dict):
            return
        if tool == "browse_public_source":
            for value in result.get("observed_ips", []) or []:
                self._add_fact_ip(facts, value, "source_ips")
            for value in result.get("observed_cidrs", []) or []:
                self._add_fact_cidr(facts, value)
            # myip.ms "All Owner IP Ranges" / "Other Sites on IP" depth lands
            # here; every provider range is real target evidence.
            for value in result.get("owner_ranges", []) or []:
                if isinstance(value, dict):
                    value = value.get("cidr") or value.get("range") or value.get("prefix")
                self._add_fact_cidr(facts, value)
            for value in result.get("observed_asns", []) or []:
                self._add_fact_asn(facts, value)
            parsed = _public_source_facts(str(result.get("body_preview") or ""))
            for value in parsed["observed_ips"]:
                self._add_fact_ip(facts, value, "source_ips")
            for value in parsed["observed_cidrs"]:
                self._add_fact_cidr(facts, value)
            for value in parsed["observed_asns"]:
                self._add_fact_asn(facts, value)
        elif tool == "inspect_owner_context":
            self._add_fact_ip(facts, result.get("ip"))
            self._add_fact_cidr(facts, result.get("cidr"))
            self._add_fact_asn(facts, result.get("asn"))
        elif tool == "list_owner_ranges":
            for value in result.get("ranges", []) or []:
                self._add_fact_cidr(facts, value)
            self._add_fact_asn(facts, result.get("asn"))
        elif tool == "masscan_liveness":
            for item in result.get("discovered", []) or []:
                if isinstance(item, dict):
                    self._add_fact_ip(facts, item.get("ip"), "live_ips")
                    self._add_fact_ip(facts, item.get("ip"), "source_ips")
        elif tool == "port_scan_live_ip":
            # A real full-port scan is durable L4 evidence: the IP and every
            # open port must stay valid even after the observation
            # window is trimmed.
            self._add_fact_ip(facts, result.get("ip"), "live_ips")
            self._add_fact_ip(facts, result.get("ip"), "source_ips")
        elif tool == "expand_live_ip":
            self._add_fact_ip(facts, result.get("ip"), "live_ips")
            self._add_fact_ip(facts, result.get("ip"), "source_ips")
        elif tool == "validate_proxy":
            self._add_fact_ip(facts, result.get("host") or result.get("ip"), "live_ips")
            self._add_fact_ip(facts, result.get("host") or result.get("ip"), "source_ips")

    def _fact_store_path(self) -> Path:
        return self.agent_dir / "facts.json"

    def _load_fact_store(self) -> dict[str, set[Any]]:
        """Restart-safe real evidence: a worker restart must not re-blind the
        hunter to L4 evidence it already paid for."""
        store: dict[str, set[Any]] = {
            "source_ips": set(),
            "ips": set(),
            "asns": set(),
            "cidrs": set(),
            "live_ips": set(),
        }
        path = self.agent_dir / "facts.json"
        if not path.exists():
            return store
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return store
        if not isinstance(payload, dict):
            return store
        for bucket in store:
            for value in payload.get(bucket) or []:
                if bucket == "cidrs":
                    self._add_fact_cidr(store, value)
                elif bucket == "asns":
                    self._add_fact_asn(store, value)
                else:
                    self._add_fact_ip(store, value, bucket)
        return store

    def _persist_fact_store(self) -> None:
        payload = {
            bucket: [str(item) for item in sorted(values, key=str)]
            for bucket, values in self._fact_store.items()
        }
        _json_write(self._fact_store_path(), payload)

    def _absorb_observation_facts(self, observation: dict[str, Any]) -> None:
        self._merge_observation_facts(self._fact_store, observation)
        self._persist_fact_store()

    def _hunt_facts(self) -> dict[str, set[Any]]:
        """Collect only facts that arrived from a real source or a real probe.

        The durable fact store keeps real evidence for the whole run; the
        observation window is trimmed for context size and must never be the
        only place where live L4 evidence lives.
        """
        facts: dict[str, set[Any]] = {
            bucket: set(values) for bucket, values in self._fact_store.items()
        }

        # The operator is an authoritative scent source. When they name a CIDR,
        # ASN or IP, the hunter may act on it instead of re-browsing from zero.
        # The brief may arrive as the agent's initial_input or as a later
        # intervene directive; both are operator voice and both must count.
        operator_texts: list[str] = []
        if self.initial_input:
            operator_texts.append(str(self.initial_input))
        for directive in self.operator_directives:
            text = str(directive.get("instruction") or directive.get("text") or "")
            if text:
                operator_texts.append(text)
        for text in operator_texts:
            for value in _PUBLIC_CIDR_RE.findall(text):
                self._add_fact_cidr(facts, value)
            for value in _PUBLIC_ASN_RE.findall(text):
                self._add_fact_asn(facts, value)
            for value in _PUBLIC_IPV4_RE.findall(text):
                self._add_fact_ip(facts, value, "source_ips")
            # An operator-stated masscan live list is real L4 evidence for the
            # current run; port scanning those IPs must not require a re-scan.
            if re.search(r"(?i)(canli|live|masscan)", text):
                for value in _PUBLIC_IPV4_RE.findall(text):
                    self._add_fact_ip(facts, value, "live_ips")

        for observation in self.observations:
            self._merge_observation_facts(facts, observation)
        return facts

    def _target_provenance_error(self, name: str, arguments: dict[str, Any]) -> str | None:
        facts = self._hunt_facts()
        if name == "inspect_owner_context":
            if str(arguments.get("ip")) not in facts["source_ips"]:
                return "public-source gövdesinde gözlenmiş IP kanıtı yok"
        elif name == "list_owner_ranges":
            if int(arguments.get("asn", 0) or 0) not in facts["asns"]:
                return "public-source veya owner kanıtında gözlenmiş ASN yok"
        elif name == "masscan_liveness":
            network = ipaddress.ip_network(str(arguments.get("cidr")), strict=False)
            source_ips = facts["source_ips"]
            if not any(ipaddress.ip_address(ip) in network for ip in source_ips) and not any(
                network.subnet_of(parent) for parent in facts["cidrs"]
            ):
                return "CIDR public-source/owner/kardeş aralığı kanıtından türemiyor"
        elif name == "port_scan_live_ip":
            ip = str(arguments.get("ip"))
            if ip not in facts["live_ips"] and ip not in facts["source_ips"]:
                return "port taraması için gerçek L4 canlı IP kanıtı yok"
        elif name == "expand_live_ip":
            ip = str(arguments.get("ip"))
            if ip not in facts["live_ips"] and ip not in facts["source_ips"]:
                return "dikey genişleme için gerçek L4 canlı IP kanıtı yok"
        elif name == "validate_proxy":
            host = str(arguments.get("ip") or arguments.get("host") or "")
            if host not in facts["live_ips"] and host not in facts["source_ips"]:
                return "L7 doğrulama için gerçek L4 canlı IP kanıtı yok"
        return None

    def _record_discovery_intent(
        self,
        decision: dict[str, Any],
        arguments: dict[str, Any],
        source_refs: list[str],
    ) -> None:
        port_fields = ("ports", "port_spec", "port_range")
        port_intent = {field: arguments[field] for field in port_fields if field in arguments}
        record = {
            "cidr": arguments.get("cidr"),
            "port_intent": port_intent,
            "provider": decision.get("provider"),
            "model": decision.get("model"),
            "action": decision.get("action"),
            "source_evidence_refs": list(source_refs),
            "port_policy_source": "var/port-araliklari/yuksek.txt",
            "allowed_port_ranges": _allowed_port_bands(),
            "created_at": _utc(),
            "executed": False,
        }
        path = self.output_dir / f"discovery-intent-{self.step:05d}.json"
        ref = _json_write(path, record)
        record["output_ref"] = ref
        self.last_tool_result = record
        self.observations.append({"tool": "discovery_intent", "result": record, "at": _utc()})
        self.observations = self.observations[-100:]
        self.emit(
            "discovery_intent_ready",
            "AI keşif niyeti canonical port politikasıyla hazırlandı; scanner çalıştırılmadı.",
            state="waiting",
            tool="masscan_liveness",
            target="vds://agent/discovery-intent",
            evidence_refs=[ref] + list(source_refs),
            output_ref=ref,
            decision={
                "action": decision.get("action"),
                "provider": decision.get("provider"),
                "model": decision.get("model"),
            },
            intent=record,
            next_action="operator review; scanner not executed",
        )

    def _outcome_path(self) -> Path:
        return self.output_dir / "outcomes.jsonl"

    def _load_recent_outcomes(self, limit: int = 20) -> list[dict[str, Any]]:
        """Restart-safe planner feedback: last real tool outcomes, not scores."""
        path = self.output_dir / "outcomes.jsonl"
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        for line in lines:
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except ValueError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    def _record_outcome(
        self,
        name: str,
        arguments: dict[str, Any],
        result: Any,
        elapsed_ms: float,
        error_class: str | None = None,
    ) -> dict[str, Any]:
        """Append the real result of one tool call for planner feedback."""
        payload = result if isinstance(result, dict) else {}
        discovered = payload.get("discovered") or []
        open_ports = payload.get("open_ports") or []
        validated_ports = payload.get("validated_ports")
        validated = payload.get("validated") or []
        probe_results = payload.get("results") or []
        egress_confirmed = bool(
            any(
                isinstance(item, dict) and item.get("egress_confirmed")
                for item in probe_results
            )
            or any(
                isinstance(item, dict) and item.get("egress_confirmed")
                for item in validated
            )
            or payload.get("egress_hits")
        )
        record = {
            "at": _utc(),
            "step": self.step,
            "tool": name,
            "arguments": _outcome_argument_summary(name, arguments),
            "l4_positive_count": len(discovered) if isinstance(discovered, list) else 0,
            "open_port_count": len(open_ports) if isinstance(open_ports, list) else 0,
            "validated_port_count": (
                int(validated_ports)
                if isinstance(validated_ports, (int, float))
                else len(validated) if isinstance(validated, list) else 0
            ),
            "l7_validated_count": len(validated) if isinstance(validated, list) else 0,
            "l7_results": [
                {
                    "protocol": item.get("protocol"),
                    "egress_confirmed": bool(item.get("egress_confirmed")),
                }
                for item in probe_results
                if isinstance(item, dict)
            ],
            "egress_confirmed": egress_confirmed,
            "error_class": error_class,
            "error": payload.get("error"),
            "elapsed_ms": round(float(elapsed_ms), 1),
            "result_summary": {
                key: payload.get(key)
                for key in (
                    "cidr",
                    "ip",
                    "port_spec",
                    "scan_range",
                    "open_port_count",
                    "validated_ports",
                    "pending_open_ports",
                    "discovered",
                )
                if key in payload
            },
        }
        path = self._outcome_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._outcome_records.append(record)
        self._outcome_records = self._outcome_records[-40:]
        return record

    def _evidence_summary(self, sample: int = 25) -> dict[str, Any]:
        """Bounded snapshot of durable real evidence for the planner."""
        return {
            bucket: {
                "count": len(values),
                "sample": [str(item) for item in sorted(values, key=str)[:sample]],
            }
            for bucket, values in self._fact_store.items()
            if values
        }

    def _invoke(self, name: str, arguments: dict[str, Any]) -> None:
        if self.stopped():
            return
        started = time.monotonic()
        self.emit(
            "tool_started",
            f"VDS aracı başladı: {name}.",
            tool=name,
            target=f"vds://agent/tool/{name}",
            decision=self.last_decision.get("action"),
            next_action="Araç sonucu bekleniyor",
            arguments=arguments,
        )
        try:
            result = self.catalog.invoke(name, arguments)
            if name == "validate_proxy":
                self._mark_port_validated(arguments)
            if name in {"port_scan_live_ip", "expand_live_ip"}:
                # Mechanical work must not wait for the planner: every open
                # port this scan/expansion produced is validated now.
                scan_host = str(result.get("ip") or "")
                scan_open_ports = [
                    int(port) for port in (result.get("open_ports") or [])
                ]
                self._register_open_ports(scan_host, scan_open_ports)
                # Validate every registered open port for this host, including
                # ports found by earlier scans that are still missing L7 proof.
                registered_ports = sorted(self._open_ports_by_host.get(scan_host, set()))
                validation = self._validate_open_ports(scan_host, registered_ports)
                result = dict(result)
                result["validated_ports"] = validation["checked"]
                result["validation_total"] = validation["total"]
                result["already_validated_ports"] = validation["already_validated"]
                result["egress_hits"] = validation["egress_hits"]
                result["pending_open_ports"] = validation["pending"]
                result["l7_results_ref"] = validation["results_ref"]
                if validation["stopped"]:
                    result["validation_stopped"] = True
                if validation["egress_hits"]:
                    result["working_note"] = (
                        str(result.get("working_note", ""))
                        + f" Otomatik L7: {len(validation['egress_hits'])} açık port gerçek çıkış verdi."
                    )
            self.last_tool_result = dict(result)
            self.observations.append({"tool": name, "result": result, "at": _utc()})
            self.observations = self.observations[-100:]
            self._absorb_observation_facts({"tool": name, "result": result})
            self._record_outcome(
                name,
                arguments,
                result,
                (time.monotonic() - started) * 1000,
            )
            ref = _json_write(self.output_dir / f"tool-{self.step:05d}-{name}.json", result)
            completion_note = str(result.get("working_note", "")) or f"VDS aracı tamamlandı: {name}."
            self.emit(
                "tool_finished",
                completion_note,
                tool=name,
                target=f"vds://agent/tool/{name}",
                evidence_refs=[ref] + [str(x) for x in result.get("evidence_refs", [])[:5]],
                output_ref=ref,
                decision=result.get("decision"),
                next_action="AI sonucu değerlendirecek",
                elapsed_ms=round((time.monotonic() - started) * 1000, 1),
                result_summary={k: v for k, v in result.items() if k not in {"body", "raw"}},
            )
            if name == "publish_proxy" and result.get("proxy"):
                proxy = dict(result["proxy"])
                self.emit(
                    "proxy_published",
                    "AI tarafından kanıt zinciriyle doğrulanmış proxy teslim edildi.",
                    state="running",
                    tool="publish_proxy",
                    target=f"vds://agent/proxy/{proxy.get('host')}:{proxy.get('port')}",
                    output_ref=ref,
                    evidence_refs=[ref, str(proxy.get("validation_ref", ""))],
                    result_summary={"proxy": proxy},
                    proxy=proxy,
                    next_action="AI yeni kanıt veya gözlem seçecek",
                )
        except Exception as exc:
            error = {"error": f"{type(exc).__name__}: {exc}", "tool": name, "at": _utc()}
            self.last_tool_result = error
            self.observations.append({"tool": name, "result": error, "at": _utc()})
            self.observations = self.observations[-100:]
            self._record_outcome(
                name,
                arguments,
                error,
                (time.monotonic() - started) * 1000,
                error_class=type(exc).__name__,
            )
            ref = _json_write(self.output_dir / f"tool-{self.step:05d}-{name}-error.json", error)
            self.emit(
                "tool_failed",
                f"VDS aracı başarısız: {name}.",
                state="failed",
                tool=name,
                target=f"vds://agent/tool/{name}",
                error=error["error"],
                evidence_refs=[ref],
                output_ref=ref,
                next_action="AI karşı hipotez üretecek",
            )

    def _observe_vds_surface(self, _args: dict[str, Any]) -> dict[str, Any]:
        stat = shutil.disk_usage(self.root)
        facts = {
            "working_note": "VDS çalışma yüzeyi gerçek işletim sistemi ve dosya gözlemiyle okundu.",
            "hostname": platform.node(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "masscan": shutil.which("masscan"),
            "ffmpeg": shutil.which("ffmpeg"),
            "workspace": str(self.repo_root),
            "agent_dir": str(self.agent_dir),
            "free_bytes": stat.free,
            "event_files": sorted(str(p.relative_to(self.agent_dir)) for p in self.agent_dir.rglob("*") if p.is_file())[-100:],
        }
        return facts

    def _read_operator_directives(self) -> list[dict[str, Any]]:
        path = self.agent_dir / "operator-directives.jsonl"
        directives: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                handle.seek(self._directive_offset)
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    self._directive_offset = handle.tell()
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        directives.append(payload)
        except FileNotFoundError:
            return []
        except OSError:
            return []
        if directives:
            self.operator_directives.extend(directives)
            self.operator_directives = self.operator_directives[-100:]
            self.observations.extend({"tool": "operator_directive", "result": item, "at": _utc()} for item in directives)
            self.observations = self.observations[-100:]
            self.emit(
                "operator_directive_received",
                "Operatör yönlendirmesi bir sonraki AI kararına eklendi.",
                state="running",
                tool="operator_control",
                target="vds://agent/directives",
                operator_action="intervene",
                directive_count=len(directives),
                directives=directives,
                next_action="AI yönlendirmeyi değerlendirecek",
            )
        return list(self.operator_directives[-20:])

    def _browse_public_source(self, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url", "")).strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("yalnız http/https kaynak kabul edilir")
        host = parsed.hostname.lower().rstrip(".")
        if any(host == dead or host.endswith("." + dead) for dead in _OLU_HOST_SON):
            raise ValueError("ölü zemin; av sayfası değil")
        if host not in _AV_SOURCE_HOSTS:
            raise ValueError("browse_public_source yalnız av hostları: RIPEstat/RDAP/bgp.he.net/myip.ms")
        if host == "myip.ms":
            from services.agentd.kahin_source import collect_myip_source

            result = collect_myip_source(url)
            screenshot_bytes = result.pop("_screenshot_bytes", b"")
            if not isinstance(screenshot_bytes, (bytes, bytearray)) or not screenshot_bytes:
                raise RuntimeError("Kahin görsel kanıt üretmedi")
            screenshot_ref = self.output_dir / f"kahin-myip-{self.step:05d}.png"
            screenshot_ref.write_bytes(bytes(screenshot_bytes))
            body = str(result.get("body_preview") or "").encode("utf-8")
            body_ref = self.output_dir / f"source-{self.step:05d}.txt"
            body_ref.write_bytes(body)
            result["sha256"] = hashlib.sha256(body).hexdigest()
            result["screenshot_ref"] = f"agent://{self.agent_id}/{screenshot_ref.relative_to(self.agent_dir)}"
            result["evidence_refs"] = [
                result["screenshot_ref"],
                f"agent://{self.agent_id}/{body_ref.relative_to(self.agent_dir)}",
            ]
            return result
        try:
            addr = ipaddress.ip_address(socket.gethostbyname(host))
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError("yerel ağ hedefi reddedildi")
        except ValueError:
            raise
        request = Request(url, headers={"User-Agent": "paidproxy-agentd/1"})
        with urlopen(request, timeout=float(args.get("timeout", 15))) as response:
            body = response.read(2_000_000)
            status = int(response.status)
            content_type = response.headers.get("content-type", "")
        digest = hashlib.sha256(body).hexdigest()
        ref = self.output_dir / f"source-{self.step:05d}.bin"
        ref.write_bytes(body)
        source_facts = _public_source_facts(body.decode("utf-8", errors="replace"))
        return {
            "working_note": f"Açık kaynak okundu: HTTP {status}, {len(body)} bayt.",
            "url": url,
            "status": status,
            "content_type": content_type,
            "sha256": digest,
            "body_preview": body[:4000].decode("utf-8", errors="replace"),
            **source_facts,
            "source_provenance": "public-source response body",
            "evidence_refs": [f"agent://{self.agent_id}/{ref.relative_to(self.agent_dir)}"],
        }

    def _inspect_owner_context(self, args: dict[str, Any]) -> dict[str, Any]:
        ip = str(args.get("ip", "")).strip()
        ipaddress.ip_address(ip)
        from proxy_pipeline.discovery.seed import lookup_seed_ip
        result = lookup_seed_ip(ip)
        result["working_note"] = f"IP sahiplik/aralık bağlamı gerçek RDAP yanıtıyla alındı: {result.get('cidr', '')}."
        return result

    def _list_owner_ranges(self, args: dict[str, Any]) -> dict[str, Any]:
        asn = int(str(args.get("asn", "")).upper().removeprefix("AS"))
        from proxy_pipeline.discovery.sibling import sibling_prefixes
        result = sibling_prefixes(asn)
        ranges = list(result.get("ipv4", []) or [])
        ref = self.output_dir / f"owner-ranges-{self.step:05d}.json"
        _json_write(ref, {"asn": asn, "ranges": ranges, "source": result.get("source")})
        return {
            "working_note": f"ASN{asn} için {len(ranges)} duyurulmuş IPv4 kardeş aralık okundu.",
            "asn": asn,
            "ranges": ranges,
            "source": result.get("source"),
            "evidence_refs": [f"agent://{self.agent_id}/{ref.relative_to(self.agent_dir)}"],
        }

    def _masscan_liveness(self, args: dict[str, Any]) -> dict[str, Any]:
        cidr = str(args.get("cidr", "")).strip()
        ipaddress.ip_network(cidr, strict=False)
        port_spec = str(args.get("port_spec") or args.get("port_range") or "").strip()
        ports = _ports_from_spec(args.get("ports"))
        # No port argument means every port: the first scan must not miss a
        # port because the planner omitted the intent.
        port_argument = port_spec or ",".join(str(port) for port in ports) or "1-65535"
        rate = int(
            args.get("rate")
            or os.environ.get("PAIDPROXY_MASSCAN_RATE", "5000")
            or "5000"
        )
        rate = max(50, min(1_000_000, rate))
        command = _masscan_command(cidr, port_argument, rate)
        output_path = self.output_dir / f"l4-{self.step:05d}.list"
        discovered = []
        with output_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            assert process.stdout is not None
            for line in process.stdout:
                if self.stopped():
                    process.terminate()
                    raise RuntimeError("operator stop during Masscan")
                output.write(line)
                text = line.strip()
                parts = text.split()
                if len(parts) >= 4 and parts[0] == "open":
                    discovered.append({"ip": parts[3], "port": int(parts[2]), "protocol": parts[1]})
            stderr = process.stderr.read() if process.stderr else ""
            return_code = process.wait()
        if return_code != 0:
            raise RuntimeError((stderr or f"masscan exit {return_code}").strip()[:2000])
        return {
            "working_note": f"L4 canlılık tamamlandı: {len(discovered)} açık uç; L7 henüz yapılmadı.",
            "cidr": cidr,
            "port_spec": port_argument,
            "rate": rate,
            "discovered": discovered,
            "evidence_refs": [f"agent://{self.agent_id}/{output_path.relative_to(self.agent_dir)}"],
            "next_action": "AI canlı IP seçip socket dikey genişleme veya L7 doğrulama kararı verecek",
        }

    def _masscan_enumerate_ports(self, ip: str, port_range: str, rate: int) -> list[int]:
        """Run masscan over the range and return the ports it reported open."""
        command = _masscan_command(f"{ip}/32", port_range.replace(" ", ""), rate)
        reported: list[int] = []
        stderr = ""
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                if self.stopped():
                    process.terminate()
                    raise RuntimeError("operator stop during port scan")
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0] == "open":
                    try:
                        reported.append(int(parts[2]))
                    except ValueError:
                        continue
            stderr = process.stderr.read() if process.stderr else ""
            return_code = process.wait()
        if return_code != 0 and not reported:
            raise RuntimeError((stderr or f"masscan exit {return_code}").strip()[:2000])
        return sorted(set(reported))

    def _port_scan_live_ip(self, args: dict[str, Any]) -> dict[str, Any]:
        """Enumerate every open TCP port on a live IP.

        Measured on the real VDS: masscan full-scans one IP in ~8s and finds
        all ports, while a pure socket scan took 250s+ and missed ports. So
        masscan enumerates, then each hit is re-confirmed with a real socket
        connect so a stale SYN result never becomes a fake open port.
        """
        ip = str(args.get("ip", "")).strip()
        ipaddress.ip_address(ip)
        # This tool's contract is a FULL scan: "live IP -> every open port".
        # Measured on the real VDS, a planner-supplied narrow range (the vendor
        # port list) silently dropped 22/80/443/5432/16866. Keep the operator's
        # request for the record but always scan the whole space.
        requested_range = str(args.get("port_range") or "1-65535").strip() or "1-65535"
        _port_intervals(requested_range)  # shape validation
        port_range = "1-65535"
        rate = int(
            args.get("rate")
            or os.environ.get("PAIDPROXY_MASSCAN_RATE", "5000")
            or "5000"
        )
        rate = max(50, min(1_000_000, rate))
        confirm_timeout = float(args.get("timeout", 1.5) or 1.5)

        reported = self._masscan_enumerate_ports(ip, port_range, rate)

        def confirm(port: int) -> tuple[int, bool]:
            if self.stopped():
                return port, False
            try:
                with socket.create_connection((ip, port), timeout=confirm_timeout):
                    return port, True
            except OSError:
                return port, False

        open_ports: list[int] = []
        if reported:
            with ThreadPoolExecutor(max_workers=max(1, min(256, len(reported)))) as pool:
                for port, ok in pool.map(confirm, sorted(set(reported))):
                    if ok:
                        open_ports.append(port)
        open_ports.sort()
        self._register_open_ports(ip, open_ports)
        result_path = self.output_dir / f"portscan-{self.step:05d}.json"
        _json_write(result_path, {
            "ip": ip,
            "open_ports": open_ports,
            "open_port_count": len(open_ports),
            "masscan_reported": sorted(set(reported)),
            "scan_range": port_range,
            "requested_range": requested_range,
            "method": "masscan+socket_confirm",
        })
        return {
            "working_note": (
                f"{ip} port taraması tamamlandı: {len(open_ports)} açık port "
                f"(masscan {len(set(reported))} bildirdi, socket doğruladı); "
                "tamamı L7 doğrulamaya gidiyor."
            ),
            "ip": ip,
            "open_ports": open_ports,
            "open_port_count": len(open_ports),
            "masscan_reported": sorted(set(reported)),
            "scan_range": port_range,
            "requested_range": requested_range,
            "method": "masscan+socket_confirm",
            "evidence_refs": [f"agent://{self.agent_id}/{result_path.relative_to(self.agent_dir)}"],
        }

    def _expand_live_ip(self, args: dict[str, Any]) -> dict[str, Any]:
        ip = str(args.get("ip", "")).strip()
        ipaddress.ip_address(ip)
        port_spec = str(args.get("port_spec") or args.get("port_range") or "").strip()
        ports = _ports_from_spec(args.get("ports"))
        if not port_spec and not ports:
            raise ValueError("AI dikey socket genişlemesi için açık port niyeti vermedi")
        ports = ports or _ports_from_spec(port_spec)
        if not ports:
            raise ValueError("dikey socket port kümesi boş")
        timeout = float(args.get("timeout", 0.6) or 0.6)
        open_ports: list[int] = []

        def probe(port: int) -> tuple[int, bool]:
            if self.stopped():
                return port, False
            try:
                with socket.create_connection((ip, port), timeout=timeout):
                    return port, True
            except OSError:
                return port, False

        workers = int(args.get("concurrency", 256) or 256)
        with ThreadPoolExecutor(max_workers=max(1, min(1024, workers))) as pool:
            futures = [pool.submit(probe, port) for port in ports]
            for future in as_completed(futures):
                port, opened = future.result()
                if opened:
                    open_ports.append(port)
        open_ports.sort()
        self._register_open_ports(ip, open_ports)
        result_path = self.output_dir / f"vertical-{self.step:05d}.json"
        _json_write(result_path, {
            "ip": ip,
            "open_ports": open_ports,
            "open_port_count": len(open_ports),
            "method": "direct_socket",
            "port_spec": port_spec or ports,
        })
        return {
            "working_note": (
                f"{ip} için doğrudan socket dikey genişleme tamamlandı: "
                f"{len(open_ports)} açık port; tamamı L7 doğrulamaya gidiyor."
            ),
            "ip": ip,
            "open_ports": open_ports,
            "open_port_count": len(open_ports),
            "method": "direct_socket",
            "port_spec": port_spec or ports,
            "evidence_refs": [f"agent://{self.agent_id}/{result_path.relative_to(self.agent_dir)}"],
        }

    def _validate_proxy(self, args: dict[str, Any]) -> dict[str, Any]:
        host = str(args.get("ip") or args.get("host") or "").strip()
        port = int(args.get("port", 0) or 0)
        if not host or not 1 <= port <= 65535:
            raise ValueError("proxy host/port eksik")
        target = self._target_from_args(args)
        protocols = args.get("protocols")
        if isinstance(protocols, str):
            protocols = [protocols]
        if not isinstance(protocols, (list, tuple)) or not protocols:
            raise ValueError("AI validate_proxy için protocols alanında açık seçim yapmalı")
        protocols = [str(protocol).strip().lower() for protocol in protocols if str(protocol).strip()]
        if not protocols:
            raise ValueError("AI validate_proxy protocols listesi boş")
        results = []
        for protocol in protocols:
            if self.stopped():
                break
            outcome = self._probe_protocol(host, port, str(protocol).lower(), target)
            results.append(outcome)
        accepted = [item for item in results if item.get("egress_confirmed")]
        safe_host = re.sub(r"[^A-Za-z0-9._-]", "_", host)
        ref_path = self.output_dir / f"validation-{self.step:05d}-{safe_host}-{port}.json"
        validation_ref = _json_write(
            ref_path,
            {
                "validation_ref": None,
                "host": host,
                "port": port,
                "target": target,
                "results": results,
                "validated": accepted,
                "observed_at": _utc(),
            },
        )
        payload = json.loads(ref_path.read_text(encoding="utf-8"))
        payload["validation_ref"] = validation_ref
        _json_write(ref_path, payload)
        return {
            "working_note": f"{host}:{port} L7 el sıkışması ve AI'nin seçtiği gerçek hedef çıkışı incelendi: {len(accepted)} protokol geçerli.",
            "host": host,
            "port": port,
            "target": target,
            "results": results,
            "validated": accepted,
            "validation_ref": validation_ref,
            "evidence_refs": [validation_ref],
        }

    @staticmethod
    def _target_from_args(args: dict[str, Any]) -> dict[str, Any]:
        raw = str(args.get("target_url") or args.get("target") or "").strip()
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("AI validate_proxy için gerçek bir target_url (http/https) vermeli")
        target_host = parsed.hostname.lower().rstrip(".")
        if any(target_host == dead or target_host.endswith("." + dead) for dead in _OLU_HOST_SON):
            raise ValueError("validation hedefi genel örnek/kimlik-sorgu sayfası olamaz")
        try:
            address = ipaddress.ip_address(socket.gethostbyname(target_host))
        except OSError as exc:
            raise ValueError(f"validation hedefi çözümlenemedi: {exc}") from exc
        if address.is_private or address.is_loopback or address.is_link_local:
            raise ValueError("validation hedefi yerel ağda olamaz")
        return {
            "url": raw,
            "scheme": parsed.scheme,
            "host": target_host,
            "port": parsed.port or (443 if parsed.scheme == "https" else 80),
            "path": parsed.path or "/",
        }

    @staticmethod
    def _read_headers(sock: socket.socket, limit: int = 8192) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data and len(data) < limit:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
        return data

    def _proxy_get(self, sock: socket.socket, target: dict[str, Any]) -> dict[str, Any]:
        """Fetch the real target through the open port and prove it is the target.

        A non-proxy web port happily answers with its own 200/404 page, so a bare
        status code is not egress evidence. The reply must carry the target's own
        payload (host echo or target-specific marker), otherwise the open port is
        just an open web server and ``egress_confirmed`` stays false.
        """
        host = str(target["host"])
        path = str(target["path"])
        sock.sendall(
            f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
            "Connection: close\r\nUser-Agent: paidproxy-agentd/1\r\n\r\n".encode()
        )
        raw = self._read_headers(sock)
        header_blob, _, buffered_body = raw.partition(b"\r\n\r\n")
        headers = header_blob
        first = headers.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
        match = re.search(r"HTTP/\d(?:\.\d)?\s+(\d+)", first)
        status = int(match.group(1)) if match else None
        body = buffered_body + self._read_body(sock, headers)
        lowered = body.decode("latin1", errors="replace").lower()
        server = ""
        for line in headers.split(b"\r\n")[1:]:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"server":
                server = value.strip().decode("latin1", errors="replace")
                break
        # The target itself must speak: httpbin echoes the caller origin, and any
        # real proxied response echoes the requested Host or a target marker.
        payload_confirms_target = bool(
            body
            and (
                host.lower() in lowered
                or '"origin"' in lowered
                or "httpbin" in lowered
                or b"<html" not in body.lower()[:512]
            )
        )
        origin_page = b"<!doctype html" in body.lower()[:64] or b"<html" in body.lower()[:64]
        return {
            "http_status": status,
            "response_line": first,
            "server": server,
            "body_preview": body[:200].decode("latin1", errors="replace"),
            "egress_confirmed": bool(
                status is not None
                and 200 <= status < 400
                and body
                and payload_confirms_target
                and not origin_page
            ),
        }

    @staticmethod
    def _read_body(sock: socket.socket, headers: bytes, limit: int = 8192) -> bytes:
        """Read a bounded response body after headers, honoring Content-Length."""
        length = 0
        for line in headers.split(b"\r\n")[1:]:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length":
                try:
                    length = int(value.strip())
                except ValueError:
                    length = 0
                break
        chunks: list[bytes] = []
        total = 0
        try:
            while total < min(limit, length or limit):
                chunk = sock.recv(min(4096, limit - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if length and total >= length:
                    break
        except OSError:
            pass
        return b"".join(chunks)

    def _probe_protocol(self, host: str, port: int, protocol: str, target: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            sock = socket.create_connection((host, port), timeout=4.0)
            sock.settimeout(4.0)
        except OSError as exc:
            return {"protocol": protocol, "stage": "connect", "error": str(exc), "egress_confirmed": False}
        try:
            if protocol == "http_connect":
                sock.sendall(
                    f"CONNECT {target['host']}:{target['port']} HTTP/1.1\r\n"
                    f"Host: {target['host']}:{target['port']}\r\n"
                    "Proxy-Connection: Keep-Alive\r\n\r\n".encode()
                )
                response = self._read_headers(sock)
                first = response.split(b"\r\n", 1)[0].decode("latin1", errors="replace")
                match = re.search(r"HTTP/\d(?:\.\d)?\s+(\d+)", first)
                status = int(match.group(1)) if match else None
                if status != 200:
                    # 407 means a REAL proxy that wants credentials; 400/404/500
                    # from a web server means the port is not a proxy at all.
                    auth_required = status == 407
                    return {
                        "protocol": protocol,
                        "stage": "connect",
                        "response_line": first,
                        "http_status": status,
                        "proxy_detected": auth_required,
                        "auth_required": auth_required,
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }
                sock = self._wrap_target_tls(sock, target)
                result = self._proxy_get(sock, target)
                result.update({
                    "protocol": protocol,
                    "stage": "l7+egress",
                    "connect_response": first,
                    "proxy_detected": True,
                    "auth_required": False,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                })
                return result
            if protocol == "socks5":
                sock.sendall(b"\x05\x01\x00")
                method = sock.recv(2)
                if method != b"\x05\x00":
                    return {
                        "protocol": protocol,
                        "stage": "handshake",
                        "response": repr(method),
                        "egress_confirmed": False,
                    }
                address = socket.gethostbyname(str(target["host"]))
                request = b"\x05\x01\x00\x01" + socket.inet_aton(address) + int(target["port"]).to_bytes(2, "big")
                sock.sendall(request)
                reply = sock.recv(10)
                if len(reply) < 2 or reply[1] != 0:
                    return {
                        "protocol": protocol,
                        "stage": "connect",
                        "response": repr(reply),
                        "egress_confirmed": False,
                    }
                sock = self._wrap_target_tls(sock, target)
                result = self._proxy_get(sock, target)
                result.update({"protocol": protocol, "stage": "l7+egress"})
                return result
            if protocol in {"socks4", "socks4a"}:
                address = socket.gethostbyname(str(target["host"]))
                request = b"\x04\x01" + int(target["port"]).to_bytes(2, "big") + socket.inet_aton(address) + b"agentd\x00"
                sock.sendall(request)
                reply = sock.recv(8)
                if len(reply) < 2 or reply[1] != 0x5A:
                    return {
                        "protocol": protocol,
                        "stage": "handshake",
                        "response": repr(reply),
                        "egress_confirmed": False,
                    }
                sock = self._wrap_target_tls(sock, target)
                result = self._proxy_get(sock, target)
                result.update({"protocol": protocol, "stage": "l7+egress"})
                return result
            return {"protocol": protocol, "stage": "unsupported", "egress_confirmed": False}
        except (OSError, TimeoutError) as exc:
            return {"protocol": protocol, "stage": "error", "error": str(exc), "egress_confirmed": False}
        finally:
            sock.close()

    @staticmethod
    def _wrap_target_tls(sock: socket.socket, target: dict[str, Any]) -> socket.socket:
        if str(target.get("scheme", "")).lower() != "https":
            return sock
        context = ssl.create_default_context()
        return context.wrap_socket(sock, server_hostname=str(target["host"]))

    def _publish_proxy(self, args: dict[str, Any]) -> dict[str, Any]:
        validation_ref = str(args.get("validation_ref", "")).strip()
        if not validation_ref:
            raise ValueError("validation_ref gerekli")
        validation_path = self._resolve_agent_ref(validation_ref)
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        if not isinstance(validation, dict) or validation.get("host") is None:
            raise ValueError("validation_ref geçerli validation kanıtı değil")
        proxies_path = self.output_dir / "validated-proxies.jsonl"
        host = str(args.get("ip") or args.get("host") or "")
        port = int(args.get("port", 0) or 0)
        protocol = str(args.get("protocol", "")).strip().lower()
        if validation.get("host") != host or int(validation.get("port", 0) or 0) != port:
            raise ValueError("publish host/port validation kanıtıyla eşleşmiyor")
        matching = [
            item for item in list(validation.get("validated", []) or validation.get("results", []) or [])
            if str(item.get("protocol", "")).lower() == protocol and bool(item.get("egress_confirmed"))
        ]
        if not matching:
            raise ValueError("publish protocol için eşleşen L7 + egress kanıtı yok")
        quality_label = str(args.get("quality_label") or args.get("classification") or "").strip()
        quality_rationale = str(args.get("quality_rationale") or args.get("rationale") or "").strip()
        if not quality_label or not quality_rationale:
            raise ValueError("AI quality_label ve quality_rationale sağlamalı")
        record = {
            "published_at": _utc(),
            "agent_id": self.agent_id,
            "validation_ref": validation_ref,
            "host": host,
            "port": port,
            "protocol": protocol,
            "quality_label": quality_label,
            "quality_rationale": quality_rationale,
            "validation_evidence": matching,
            "target": validation.get("target"),
            "evidence": list(args.get("evidence", []) or []),
        }
        if not record["host"] or not 1 <= record["port"] <= 65535 or not record["protocol"]:
            raise ValueError("teslim kaydı host/port/protocol eksik")
        _append_jsonl(proxies_path, record)
        return {
            "working_note": f"Doğrulanmış proxy teslim kuyruğuna yazıldı: {record['host']}:{record['port']}.",
            "proxy": record,
            "evidence_refs": [f"agent://{self.agent_id}/{proxies_path.relative_to(self.agent_dir)}"],
            "output_ref": f"agent://{self.agent_id}/{proxies_path.relative_to(self.agent_dir)}",
        }

    def _resolve_agent_ref(self, reference: str) -> Path:
        prefix = f"agent://{self.agent_id}/"
        if not reference.startswith(prefix):
            raise ValueError("artifact referansı bu ajana ait değil")
        relative = reference[len(prefix):]
        if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("artifact referansı geçersiz")
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", relative):
            raise ValueError("artifact referansı güvenli karakterler içermiyor")
        target_path = (self.agent_dir / relative).resolve()
        try:
            target_path.relative_to(self.agent_dir)
        except ValueError as exc:
            raise ValueError("artifact ajan dizini dışına taşıyor") from exc
        if not target_path.is_file():
            raise ValueError("artifact dosyası bulunamadı")
        return target_path

    @staticmethod
    def _text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            return "; ".join(str(item) for item in value[:3])
        return str(value)[:500]

    @staticmethod
    def _first(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return str(value[0])[:500] if value else ""
        return str(value or "")[:500]

    @staticmethod
    def _decision_evidence(decision: dict[str, Any]) -> list[str]:
        values = decision.get("evidence") or []
        return [str(value) for value in values[:5]]
