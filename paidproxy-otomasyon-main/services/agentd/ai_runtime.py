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

from proxy_pipeline.agents.ai_havuz import HavuzBeyni
from proxy_pipeline.domain.models import DecisionContext
from proxy_pipeline.tarama_plani import bant_listesi


CONTROLLED_TOOLS = {
    "observe_vds_surface",
    "browse_public_source",
    "inspect_owner_context",
    "list_owner_ranges",
    "masscan_liveness",
    "expand_live_ip",
    "validate_proxy",
    "publish_proxy",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


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
    """Build the real L4 command, elevating only when masscan lacks capabilities."""
    binary = shutil.which("masscan") or "masscan"
    command = [binary, cidr, "-p", port_spec, "--wait", "0", "-oL", "-", "--rate", str(rate)]
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

_HUNT_NOTEBOOK_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "var" / "port-araliklari" / "av-defteri.txt",
    Path(__file__).resolve().parents[2] / "config" / "hunt" / "av-defteri.txt",
)
_HUNT_NOTEBOOK = _HUNT_NOTEBOOK_CANDIDATES[0]


def _read_hunt_notebook(path: Path | None = None) -> dict[str, Any]:
    """Operator hunt notebook: port/band scent that must be read on every decision."""
    if path:
        notebook = Path(path)
    else:
        notebook = next(
            (candidate for candidate in _HUNT_NOTEBOOK_CANDIDATES if candidate.is_file()),
            _HUNT_NOTEBOOK_CANDIDATES[0],
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


def _hunter_instruction(observations: list[dict[str, Any]]) -> str:
    """Keep the AI moving from runtime preflight into real public-source hunting."""
    runtime_seen = any(item.get("tool") == "observe_vds_surface" for item in observations)
    source_seen = any(
        item.get("tool") == "browse_public_source"
        and isinstance(item.get("result"), dict)
        and 200 <= int(item["result"].get("status", 0) or 0) < 400
        for item in observations
    )
    if source_seen:
        return (
            "Public av kaynağı kanıtı artık mevcut. observe_vds_surface tekrar seçme; "
            "kaynak gövdesindeki gözlenmiş IP/org/ASN sinyalinden inspect_owner_context "
            "veya list_owner_ranges seç, sonra yalnız gerekçeli tek ilk dişe geç. "
            "Genel DNS/bootstrap hedeflerini başlangıç kokusu sayma; "
            "masscan discovered boşsa expand_live_ip seçme."
        )
    if runtime_seen:
        return (
            "VDS runtime yüzeyi zaten gözlendi; observe_vds_surface tekrar seçme. "
            "Şimdi browse_public_source ile yalnız av hostlarından birini seç: "
            "bgp.he.net, stat.ripe.net, rdap.* veya myip.ms. "
            "Genel web araması, örnek sayfalar veya DNS/bootstrap hedefleri kullanma; "
            "kaynak kanıtı olmadan CIDR/ASN/port uydurma."
        )
    return "İlk turda runtime yüzeyini en fazla bir kez gözle; sonra public-source koku araştırmasına geç."


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
    allowed = _port_intervals(_allowed_port_bands())
    requested = _port_intervals(value)
    for start, end in requested:
        if not any(start >= low and end <= high for low, high in allowed):
            raise ValueError("port niyeti vekil ısırığı veya yüksek bant dışında")




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

    if name in {"masscan_liveness", "expand_live_ip"}:
        if name == "masscan_liveness":
            raw_cidr = str(arguments.get("cidr") or "").strip()
            if not raw_cidr:
                raise ValueError("masscan_liveness.cidr gerekli")
            network = ipaddress.ip_network(raw_cidr, strict=False)
            if network.version != 4 or not network.is_global:
                raise ValueError("masscan_liveness.cidr publicly routable IPv4 olmalı")
            if network.prefixlen < 24:
                raise ValueError("masscan_liveness.cidr en fazla /24; dağı ilk kanda tarama")
            result["cidr"] = network.with_prefixlen
        else:
            raw_ip = str(arguments.get("ip") or "").strip()
            if not raw_ip:
                raise ValueError("expand_live_ip.ip gerekli")
            result["ip"] = str(ipaddress.ip_address(raw_ip))
        field, ports = _validated_port_intent(arguments)
        result[field] = ports
        if name == "masscan_liveness":
            intervals = _port_intervals(ports)
            if len(intervals) != 1 or intervals[0][0] != intervals[0][1]:
                raise ValueError("masscan_liveness tek ilk port ister; dikey genişleme expand_live_ip'e aittir")
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
            if not 0 < timeout <= 10:
                raise ValueError("timeout 0..10 arasında olmalı")
            result["timeout"] = timeout
        if arguments.get("concurrency") is not None:
            try:
                concurrency = int(arguments["concurrency"])
            except (TypeError, ValueError):
                raise ValueError("concurrency sayısal olmalı") from None
            if not 1 <= concurrency <= 1024:
                raise ValueError("concurrency 1..1024 arasında olmalı")
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
        self._decision_phase = "hunt"
        self._runtime_preflight_done = False
        self._source_decision_attempts = 0
        self._source_successes = 0
        self._intent_decision_attempts = 0
        self._source_decision_budget = 3
        self._intent_decision_budget = 4
        self._register_tools()

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
        while not self.stopped():
            self._read_operator_directives()
            self.step += 1
            decision = self._decide()
            if decision is None:
                idle_rounds += 1
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


    def _decide(self) -> dict[str, Any] | None:
        snapshot = {
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
                "dikey genişleme için expand_live_ip socket aracını seç. Sabit skor üretme. "
                "Gerçek bir HTTP(S) hedefini target_url alanında kendin seçmeden L7 doğrulama "
                "isteme. validate_proxy için protocols alanında hangi protokolleri deneyeceğini "
                "açıkça seç; protokol listesi eksikse araç çağrısı yapma. publish_proxy için "
                "validation_ref, host, port, protocol, quality_label ve quality_rationale "
                "alanlarını kanıtla. "
                "Avcısın: sahiplik ve kardeş aralıkla kokla; örnek sayfa, genel web araması "
                "ve DNS/bootstrap hedefi ölü zemindir. Koku yoksa ısırma. İlk ısırık tek vekil dişi "
                "(squid→3128, socks→1080). Kan varsa aynı dişle komşu, dağı yutma. "
                "masscan cidr en fazla /24. Çıkışsız açık port vekil değil."
            ) + " " + _hunter_instruction(self.observations),
        }
        context = DecisionContext(
            "agent_action",
            f"{self.agent_id}:{self.step}",
            snapshot,
            "ai-runtime-dynamic",
            "vds-agentd",
            prompt_version="agentd-hunter-soul-1",
            tool_version="catalog-6",
        )
        try:
            raw = HavuzBeyni().decide(context)
        except Exception as exc:
            self.emit(
                "ai_unavailable",
                f"AI kararı alınamadı: {type(exc).__name__}.",
                state="waiting",
                tool="ai_planner",
                target="vds://agent/decision",
                error=f"{type(exc).__name__}: {exc}",
                next_action="AI sağlayıcısı yeniden denenecek",
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
            # list of candidate IPs) each carry their own arguments.
            names = [
                {"name": name, "tool_arguments": arguments}
                for name, arguments in self._flat_tool_arguments(decision)
            ]
        resource_plan = decision.get("resource_plan") or {}
        args_by_tool = resource_plan.get("tool_arguments", {}) if isinstance(resource_plan, dict) else {}
        if not isinstance(args_by_tool, dict):
            args_by_tool = {}

        result: list[tuple[str, dict[str, Any]]] = []
        errors: list[str] = []
        provenance_deferred: list[str] = []
        browse_requested = any(
            isinstance(candidate, str) and candidate == "browse_public_source"
            or isinstance(candidate, dict)
            and str(candidate.get("name") or candidate.get("tool") or "").strip() == "browse_public_source"
            for candidate in names
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

    def _hunt_facts(self) -> dict[str, set[Any]]:
        """Collect only facts that arrived from a real source or a real probe."""
        facts: dict[str, set[Any]] = {
            "source_ips": set(),
            "ips": set(),
            "asns": set(),
            "cidrs": set(),
            "live_ips": set(),
        }

        def add_ip(value: Any, bucket: str = "ips") -> None:
            try:
                address = ipaddress.ip_address(str(value).strip())
            except ValueError:
                return
            if address.version == 4 and address.is_global:
                facts[bucket].add(str(address))
                facts["ips"].add(str(address))

        def add_asn(value: Any) -> None:
            try:
                asn = int(str(value).strip().upper().removeprefix("AS"))
            except (TypeError, ValueError):
                return
            if 1 <= asn <= 4294967295:
                facts["asns"].add(asn)

        def add_cidr(value: Any) -> None:
            try:
                network = ipaddress.ip_network(str(value).strip(), strict=False)
            except ValueError:
                return
            if network.version == 4 and network.is_global:
                facts["cidrs"].add(network)

        # The operator is an authoritative scent source. When they name a CIDR,
        # ASN or IP, the hunter may act on it instead of re-browsing from zero.
        for directive in self.operator_directives:
            text = str(directive.get("instruction") or directive.get("text") or "")
            if not text:
                continue
            for value in _PUBLIC_CIDR_RE.findall(text):
                add_cidr(value)
            for value in _PUBLIC_ASN_RE.findall(text):
                add_asn(value)
            for value in _PUBLIC_IPV4_RE.findall(text):
                add_ip(value, "source_ips")

        for observation in self.observations:
            tool = observation.get("tool")
            result = observation.get("result")
            if not isinstance(result, dict):
                continue
            if tool == "browse_public_source":
                for value in result.get("observed_ips", []) or []:
                    add_ip(value, "source_ips")
                for value in result.get("observed_cidrs", []) or []:
                    add_cidr(value)
                for value in result.get("observed_asns", []) or []:
                    add_asn(value)
                parsed = _public_source_facts(str(result.get("body_preview") or ""))
                for value in parsed["observed_ips"]:
                    add_ip(value, "source_ips")
                for value in parsed["observed_cidrs"]:
                    add_cidr(value)
                for value in parsed["observed_asns"]:
                    add_asn(value)
            elif tool == "inspect_owner_context":
                add_ip(result.get("ip"))
                add_cidr(result.get("cidr"))
                add_asn(result.get("asn"))
            elif tool == "list_owner_ranges":
                for value in result.get("ranges", []) or []:
                    add_cidr(value)
                add_asn(result.get("asn"))
            elif tool == "masscan_liveness":
                for item in result.get("discovered", []) or []:
                    if isinstance(item, dict):
                        add_ip(item.get("ip"), "live_ips")
            elif tool == "expand_live_ip":
                add_ip(result.get("ip"), "live_ips")
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
        elif name == "expand_live_ip":
            if str(arguments.get("ip")) not in facts["live_ips"]:
                return "dikey genişleme için gerçek L4 canlı IP kanıtı yok"
        elif name == "validate_proxy":
            host = str(arguments.get("ip") or arguments.get("host") or "")
            if host not in facts["live_ips"]:
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
            self.last_tool_result = dict(result)
            self.observations.append({"tool": name, "result": result, "at": _utc()})
            self.observations = self.observations[-100:]
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
            if name == "publish_proxy" and result.get("candidate"):
                candidate = dict(result["candidate"])
                self.emit(
                    "proxy_published",
                    "AI tarafından kanıt zinciriyle doğrulanmış proxy teslim edildi.",
                    state="running",
                    tool="publish_proxy",
                    target=f"vds://agent/proxy/{candidate.get('host')}:{candidate.get('port')}",
                    output_ref=ref,
                    evidence_refs=[ref, str(candidate.get("validation_ref", ""))],
                    result_summary={"candidate": candidate},
                    proxy=candidate,
                    next_action="AI yeni kanıt veya gözlem seçecek",
                )
        except Exception as exc:
            error = {"error": f"{type(exc).__name__}: {exc}", "tool": name, "at": _utc()}
            self.last_tool_result = error
            self.observations.append({"tool": name, "result": error, "at": _utc()})
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
        if not port_spec and not ports:
            raise ValueError("AI masscan için açık port niyeti vermedi")
        first_bite_ports = _ports_from_spec(port_spec or args.get("ports"))
        if len(first_bite_ports) != 1:
            raise ValueError("masscan_liveness tek ilk port ister; dikey genişleme expand_live_ip'e aittir")
        rate = int(args.get("rate", 1000) or 1000)
        rate = max(50, min(1_000_000, rate))
        port_argument = port_spec or ",".join(str(port) for port in ports)
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
            "port_spec": port_spec or ports,
            "rate": rate,
            "discovered": discovered,
            "evidence_refs": [f"agent://{self.agent_id}/{output_path.relative_to(self.agent_dir)}"],
            "next_action": "AI canlı IP seçip socket dikey genişleme veya L7 doğrulama kararı verecek",
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
        result_path = self.output_dir / f"vertical-{self.step:05d}.json"
        _json_write(result_path, {"ip": ip, "ports": open_ports, "method": "direct_socket", "port_spec": port_spec or ports})
        return {
            "working_note": f"{ip} için doğrudan socket dikey genişleme tamamlandı: {len(open_ports)} port açık.",
            "ip": ip,
            "open_ports": open_ports,
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
        ref_path = self.output_dir / f"validation-{self.step:05d}.json"
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
        """Fetch the real target through the candidate and prove it is the target.

        A non-proxy web port happily answers with its own 200/404 page, so a bare
        status code is not egress evidence. The reply must carry the target's own
        payload (host echo or target-specific marker), otherwise the candidate is
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
                    return {
                        "protocol": protocol,
                        "stage": "connect",
                        "response_line": first,
                        "http_status": status,
                        "egress_confirmed": False,
                        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
                    }
                sock = self._wrap_target_tls(sock, target)
                result = self._proxy_get(sock, target)
                result.update({
                    "protocol": protocol,
                    "stage": "l7+egress",
                    "connect_response": first,
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
        candidates_path = self.output_dir / "validated-candidates.jsonl"
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
        _append_jsonl(candidates_path, record)
        return {
            "working_note": f"Doğrulanmış proxy teslim kuyruğuna yazıldı: {record['host']}:{record['port']}.",
            "candidate": record,
            "evidence_refs": [f"agent://{self.agent_id}/{candidates_path.relative_to(self.agent_dir)}"],
            "output_ref": f"agent://{self.agent_id}/{candidates_path.relative_to(self.agent_dir)}",
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
        candidate = (self.agent_dir / relative).resolve()
        try:
            candidate.relative_to(self.agent_dir)
        except ValueError as exc:
            raise ValueError("artifact ajan dizini dışına taşıyor") from exc
        if not candidate.is_file():
            raise ValueError("artifact dosyası bulunamadı")
        return candidate

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
