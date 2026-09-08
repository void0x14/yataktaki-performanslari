from __future__ import annotations

from pathlib import Path

from proxy_pipeline.decision.service import DecisionService
from proxy_pipeline.domain.models import DecisionContext
from proxy_pipeline.modes.registry import ModeManifest, ModeRegistry
from proxy_pipeline.persistence.db import connect
from proxy_pipeline.persistence.payloads import PayloadStore
from proxy_pipeline.persistence.writer import DBWriter
from proxy_pipeline.pipeline import ControlPlane
from proxy_pipeline.sources.catalog import SourceCatalog, SourceMetadata
from proxy_pipeline.sources.connectors import StaticConnector


class Route:
    version = "r1"

    def decide(self, context):
        return {
            "action": "sample",
            "targets": [{"cidr": "1.1.1.0/28", "ports": [3128], "protocols": ["http_connect"]}],
            "resource_plan": {"addresses": 8},
            "stop_condition": {"when": "evidence.ready"},
            "items": [
                {
                    "candidate_id": context.candidate_id,
                    "action": "sample",
                    "targets": [{"cidr": "1.1.1.0/28", "ports": [3128]}],
                    "order_index": 0,
                    "resource_allocation": {"addresses": 8},
                    "stop_expression": {"when": "evidence.ready"},
                }
            ],
        }


def test_decision_to_manifest_to_segment(tmp_path: Path):
    db = connect(tmp_path / "pipeline.sqlite3")
    writer = DBWriter(db)
    payloads = PayloadStore(tmp_path / "payloads")
    catalog = SourceCatalog()
    catalog.register(
        StaticConnector(
            SourceMetadata("fixture", "test", "static", "local", enabled=True),
            [{"prefix": "1.1.1.0/24"}],
        )
    )
    modes = ModeRegistry()
    modes.register(ModeManifest("single-agent", "single_agent", "1", {}))
    modes.activate("single-agent")
    plane = ControlPlane(
        catalog,
        modes,
        DecisionService([Route()], writer=writer, payload_store=payloads),
        writer=writer,
        payloads=payloads,
        var_root=tmp_path / "var",
    )
    context = DecisionContext("candidate", "c-1", {"prefix": "1.1.1.0/24"}, "s1", "1")
    record, manifest = plane.request_decision(context, technical_profile={"name": "default"})
    assert record.decision.decision_id == manifest.decision_id
    segments = plane.materialize_segments(manifest)
    assert segments[0].item_count == 1
    row = db.execute("select count(*) as n from execution_manifests").fetchone()
    assert row["n"] == 1
