"""Calisan ornek ajan. Uretim beyni degil. Kopyala, tak.py'ye tasi, doldur.

PIPELINE_AJAN=proxy_pipeline.agents.ornek:OrnekAjan
"""

from __future__ import annotations


class OrnekAjan:
    version = "ornek-1"

    def decide(self, context) -> dict:
        snap = context.snapshot or {}
        cidr = snap.get("cidr") or snap.get("prefix") or snap.get("aday") or context.candidate_id
        ports = snap.get("ports") or [3128, 8080, 1080]
        protocols = snap.get("protocols") or ["http_connect", "socks5"]
        target = {"cidr": str(cidr), "ports": [int(p) for p in ports], "protocols": list(protocols)}
        if snap.get("asn") is not None:
            target["asn"] = int(snap["asn"])
        return {
            "action": snap.get("action") or "sample",
            "targets": [target],
            "resource_plan": {"addresses": snap.get("addresses") or 256},
            "stop_condition": {"when": "evidence.ready"},
            "items": [
                {
                    "candidate_id": context.candidate_id,
                    "action": snap.get("action") or "sample",
                    "targets": [target],
                    "order_index": 0,
                    "resource_allocation": {"addresses": snap.get("addresses") or 256},
                    "stop_expression": {"when": "evidence.ready"},
                }
            ],
        }
