"""Scanned Ranges Ledger (Av Defteri Muhasebesi) — Duplicate Prevention.

Enforces Building Block 10 (Yapı Taşı 10):
Guarantees that the autonomous agent never enters a duplicate scanning loop.
An IP range and port combination is NEVER scanned twice unless:
1. A new BGP prefix is announced by the upstream AS.
2. The operator explicitly adds a new port or directive to the hunt notebook.

Thread-safe and atomic file persistence.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
from typing import Any

logger = logging.getLogger("agentd.ledger")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScannedLedger:
    def __init__(self, ledger_path: Path | str) -> None:
        self.path = Path(ledger_path)
        self.lock = threading.Lock()
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    def _make_key(self, cidr: str, port: int) -> str:
        return f"{str(cidr).strip().lower()}:{int(port)}"

    def _load(self) -> None:
        with self.lock:
            if not self.path.exists():
                self._records = {}
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._records = data.get("scans", {})
            except Exception as exc:
                logger.warning(f"Failed to load ledger from {self.path}: {exc}")
                self._records = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        payload = {
            "updated_at": _utc_iso(),
            "total_entries": len(self._records),
            "scans": self._records,
        }
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def is_scanned(self, cidr: str, port: int) -> bool:
        """Check if this CIDR and port pair has already been scanned."""
        key = self._make_key(cidr, port)
        with self.lock:
            return key in self._records

    def record_scan(
        self,
        asn: str,
        cidr: str,
        ports: list[int] | int,
        agent_id: str = "",
        found_open_count: int = 0,
        live_proxies_count: int = 0,
    ) -> None:
        """Record a completed scan for one or more ports on a CIDR."""
        port_list = [ports] if isinstance(ports, int) else list(ports)
        now = _utc_iso()
        with self.lock:
            for port in port_list:
                key = self._make_key(cidr, port)
                self._records[key] = {
                    "asn": str(asn).strip().upper(),
                    "cidr": str(cidr).strip(),
                    "port": int(port),
                    "scanned_at": now,
                    "agent_id": agent_id,
                    "found_open_count": found_open_count,
                    "live_proxies_count": live_proxies_count,
                }
            self._save()

    def filter_unscanned_ports(self, cidr: str, candidate_ports: list[int]) -> list[int]:
        """Filter out candidate ports that have already been scanned for this CIDR."""
        with self.lock:
            return [p for p in candidate_ports if self._make_key(cidr, p) not in self._records]

    def filter_unscanned_cidrs(self, candidate_cidrs: list[str], port: int) -> list[str]:
        """Filter out CIDRs that have already been scanned for this port."""
        with self.lock:
            return [c for c in candidate_cidrs if self._make_key(c, port) not in self._records]

    def get_stats(self) -> dict[str, Any]:
        """Return ledger accounting summary."""
        with self.lock:
            asns = {entry.get("asn") for entry in self._records.values() if entry.get("asn")}
            cidrs = {entry.get("cidr") for entry in self._records.values() if entry.get("cidr")}
            total_open = sum(int(entry.get("found_open_count", 0)) for entry in self._records.values())
            total_live = sum(int(entry.get("live_proxies_count", 0)) for entry in self._records.values())
            return {
                "total_scans": len(self._records),
                "unique_asns": len(asns),
                "unique_cidrs": len(cidrs),
                "total_open_ports_found": total_open,
                "total_live_proxies_found": total_live,
            }
