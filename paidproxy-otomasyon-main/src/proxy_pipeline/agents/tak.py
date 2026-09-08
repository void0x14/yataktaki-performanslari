"""AJAN TAKMA NOKTASI — senin tasakli hedef secimin buraya girer.

Sen eskiden myip.ms / BGP / sezgi ile ASN-prefix-port secerdin.
O is Asama 1. Bu dosya o isi yapan beyin.

Yapman gereken:

    class BenimAjan:
        version = "1"

        def decide(self, context):
            # context.snapshot = aday kanitlari (ASN, prefix, gecmis, kaynak ozeti)
            return {
                "action": "sample",          # research|sample|expand|full_scan|defer|drop|reassess|deep_test
                "targets": [{
                    "cidr": "1.2.3.0/24",
                    "ports": [3128, 8080, 1080],
                    "protocols": ["http_connect", "socks5"],
                }],
                "resource_plan": {"addresses": 256},
                "stop_condition": {"when": "evidence.ready"},
                "items": [{
                    "candidate_id": context.candidate_id,
                    "action": "sample",
                    "targets": [{"cidr": "1.2.3.0/24", "ports": [3128]}],
                    "order_index": 0,
                    "resource_allocation": {"addresses": 256},
                    "stop_expression": {"when": "evidence.ready"},
                }],
            }

Sonra asagida:

    ajan = BenimAjan()

Veya ortam:

    PIPELINE_AJAN=modul:Sinif
"""

from __future__ import annotations

ajan = None
