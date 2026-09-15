"""Grounded Reconnaissance and Threat Intelligence Module for PaidProxy.

Provides real network intelligence to eliminate guesswork:
1. BGP announced prefixes query via RIPEstat API (stat.ripe.net).
2. Reverse DNS / PTR pattern sampler to identify proxy cluster patterns.
3. Target classification adhering to the user's 3-tier priority hierarchy:
   - Priority 1: High-yield DC kovan (unmanaged hosting/squid/3proxy).
   - Priority 2: Long-lived stable DC/Residential forward proxies.
   - Priority 3: 4G/5G mobile / Residential dynamic pools.
   - Prohibited / Dead Ground: Cloudflare, Google, Azure, AWS omurga, banks.
4. Pilot slice (sampling) & initial tooth (port) recommendation.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("agentd.recon")

DEAD_GROUND_ASNS = {
    13335,  # Cloudflare
    15169,  # Google
    8075,   # Microsoft
    16509,  # Amazon
    20940,  # Akamai
    54113,  # Fastly
}

DEAD_GROUND_KEYWORDS = [
    "cloudflare",
    "google",
    "microsoft",
    "amazon",
    "akamai",
    "fastly",
    "bank",
    "military",
    "defense",
]

SQUID_HOSTING_KEYWORDS = [
    "hosting",
    "datacenter",
    "colocation",
    "vps",
    "dedicated",
    "reseller",
    "cloud",
    "server",
    "squid",
    "cache",
]

RESIDENTIAL_KEYWORDS = [
    "broadband",
    "telecom",
    "dialup",
    "adsl",
    "vdsl",
    "fiber",
    "ftth",
    "pppoe",
    "dynamic",
    "user",
    "subscriber",
    "pool",
]


def clean_asn(raw_asn: str | int) -> int:
    """Normalize ASN representation like 'AS209207' or '209207' to integer 209207."""
    s = str(raw_asn).strip().upper()
    if s.startswith("AS"):
        s = s[2:]
    return int(s)


def fetch_bgp_announced_prefixes(asn: str | int, timeout: float = 6.0) -> list[str]:
    """Fetch real-world BGP announced prefixes from RIPEstat public API."""
    num_asn = clean_asn(asn)
    url = f"https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS{num_asn}"
    req = urllib.request.Request(url, headers={"User-Agent": "paidproxy-recon/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            prefixes_data = data.get("data", {}).get("prefixes", [])
            prefixes = [str(item.get("prefix")) for item in prefixes_data if item.get("prefix")]
            return sorted(list(set(prefixes)), key=lambda p: ipaddress.ip_network(p).prefixlen)
    except Exception as exc:
        logger.warning(f"RIPEstat BGP query failed for AS{num_asn}: {exc}")
        return []


def fetch_as_holder(asn: str | int, timeout: float = 6.0) -> str:
    """Registered holder/org name for an ASN via RIPEstat as-overview."""
    num_asn = clean_asn(asn)
    url = f"https://stat.ripe.net/data/as-overview/data.json?resource=AS{num_asn}"
    req = urllib.request.Request(url, headers={"User-Agent": "paidproxy-recon/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {})
        return str(data.get("holder") or "")
    except Exception as exc:
        logger.warning(f"RIPEstat as-overview query failed for AS{num_asn}: {exc}")
        return ""


def fetch_network_info(ip: str, timeout: float = 6.0) -> dict[str, Any]:
    """Resolve an IP to prefix, origin ASN and holder via RIPEstat network-info.

    RDAP returns netblock handles without an origin ASN; the announced prefix
    and origin ASN come from the routing view so recon can proceed grounded.
    """
    info: dict[str, Any] = {"ip": ip, "asn": None, "prefix": "", "holder": ""}
    url = f"https://stat.ripe.net/data/network-info/data.json?resource={ip}"
    req = urllib.request.Request(url, headers={"User-Agent": "paidproxy-recon/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data", {})
    except Exception as exc:
        logger.warning(f"RIPEstat network-info query failed for {ip}: {exc}")
        return info
    info["prefix"] = str(data.get("prefix") or "")
    asns = data.get("asns") or []
    if asns:
        info["asn"] = clean_asn(asns[0])
        info["holder"] = fetch_as_holder(int(info["asn"]), timeout=timeout)
    return info


def sample_reverse_dns(
    cidr: str,
    max_samples: int = 5,
    timeout: float = 1.0,
) -> list[dict[str, str]]:
    """Sample reverse DNS (PTR) records for IP addresses within a CIDR prefix."""
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return []

    hosts = list(net.hosts())
    if not hosts:
        hosts = [net.network_address]

    step = max(1, len(hosts) // max_samples)
    sampled_ips = [str(hosts[i]) for i in range(0, len(hosts), step)][:max_samples]

    results = []
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        for ip in sampled_ips:
            try:
                hostname, _, _ = socket.gethostbyaddr(ip)
                results.append({"ip": ip, "ptr": hostname})
            except (socket.herror, socket.gaierror, OSError):
                results.append({"ip": ip, "ptr": ""})
    finally:
        socket.setdefaulttimeout(old_timeout)

    return results


def classify_target(
    asn: str | int,
    org_name: str,
    announced_prefixes: list[str] | None = None,
    ptr_records: list[str] | None = None,
) -> dict[str, Any]:
    """Classify target value, priority, and ground safety based on the 10 invariant building blocks."""
    num_asn = clean_asn(asn)
    org_lower = str(org_name).lower()

    # Check dead ground
    if num_asn in DEAD_GROUND_ASNS or any(k in org_lower for k in DEAD_GROUND_KEYWORDS):
        return {
            "asn": f"AS{num_asn}",
            "org": org_name,
            "classification": "dead_ground",
            "priority": 99,
            "is_targetable": False,
            "rationale": "Cloudflare/CDN/Omurga devleri üzerinde açık vekil avlanmaz (Ölü zemin yasağı).",
            "recommended_tooth": None,
        }

    # Detect high-yield DC kovan
    is_hosting = any(k in org_lower for k in SQUID_HOSTING_KEYWORDS)
    is_residential = any(k in org_lower for k in RESIDENTIAL_KEYWORDS)

    if ptr_records:
        ptr_blob = " ".join(ptr_records).lower()
        if any(k in ptr_blob for k in ["dyn", "pool", "dsl", "broadband", "cpe"]):
            is_residential = True
        if any(k in ptr_blob for k in ["vps", "server", "host", "node"]):
            is_hosting = True

    if is_hosting and not is_residential:
        return {
            "asn": f"AS{num_asn}",
            "org": org_name,
            "classification": "datacenter_high_yield",
            "priority": 1,
            "is_targetable": True,
            "rationale": "Unmanaged hosting/VPS/Colo sağlayıcısı. Unutulmuş Squid/3proxy kovanı barındırma ihtimali yüksek.",
            "recommended_tooth": 3128,  # Squid first
            "alternative_teeth": [8080, 10000, 3129],
        }

    if is_residential:
        return {
            "asn": f"AS{num_asn}",
            "org": org_name,
            "classification": "residential_pool",
            "priority": 2,
            "is_targetable": True,
            "rationale": "Broadband/PPPoE/FTTH dinamik abone havuzu. CPE router veya açık SOCKS gateway olma potansiyeli yüksek.",
            "recommended_tooth": 1080,  # SOCKS5 first
            "alternative_teeth": [7777, 7000, 823, 6060],
        }

    # Default fallback
    return {
        "asn": f"AS{num_asn}",
        "org": org_name,
        "classification": "general_isp",
        "priority": 3,
        "is_targetable": True,
        "rationale": "Genel otonom sistem. Port kokusu genel ürün portlarından denenmeli.",
        "recommended_tooth": 8080,
        "alternative_teeth": [8000, 10000, 12323, 3128],
    }


def plan_grounded_hunt(
    asn: str | int,
    org_name: str,
    prefixes: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble a complete grounded hunt strategy for an autonomous agent."""
    num_asn = clean_asn(asn)
    announced = prefixes or fetch_bgp_announced_prefixes(num_asn)
    classification = classify_target(num_asn, org_name, announced)

    if not classification["is_targetable"]:
        return {
            "is_targetable": False,
            "classification": classification,
            "action": "abandon",
            "reason": classification["rationale"],
        }

    if not announced:
        return {
            "is_targetable": False,
            "classification": classification,
            "action": "no_announced_prefixes",
            "reason": f"AS{num_asn} için anons edilmiş BGP prefix bulunamadı.",
        }

    # Select pilot slice: prefer the most specific /24 or /22 subnet for initial pilot sniffing
    candidate_subnets = [p for p in announced if 18 <= ipaddress.ip_network(p).prefixlen <= 24]
    if candidate_subnets:
        # Sort by prefixlen descending (e.g. /24 before /21) so initial sniff is tight and fast
        pilot_prefix = max(candidate_subnets, key=lambda p: ipaddress.ip_network(p).prefixlen)
    else:
        pilot_prefix = announced[0]

    return {
        "is_targetable": True,
        "asn": f"AS{num_asn}",
        "org": org_name,
        "classification": classification["classification"],
        "priority": classification["priority"],
        "pilot_prefix": pilot_prefix,
        "all_announced_prefixes": announced,
        "initial_tooth": classification["recommended_tooth"],
        "alternative_teeth": classification.get("alternative_teeth", []),
        "masscan_rate": 5000 if ipaddress.ip_network(pilot_prefix).num_addresses <= 1024 else 3500,
        "masscan_wait": 3,
        "socket_timeout": 1.5,
        "rationale": classification["rationale"],
    }
