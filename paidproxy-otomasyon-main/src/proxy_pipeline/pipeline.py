from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from proxy_pipeline.context.builder import ContextBuilder
from proxy_pipeline.decision.service import DecisionBlocked, DecisionService
from proxy_pipeline.domain.events import Event
from proxy_pipeline.domain.models import DecisionContext, ExecutionManifest
from proxy_pipeline.feedback import FeedbackStore
from proxy_pipeline.manifests.builder import ManifestBuilder
from proxy_pipeline.modes.registry import ModeRegistry
from proxy_pipeline.persistence.payloads import PayloadStore
from proxy_pipeline.persistence.writer import DBWriter
from proxy_pipeline.queue.manager import SegmentQueue
from proxy_pipeline.queue.segments import Segment, write_segment_items
from proxy_pipeline.queue.spool import AppendOnlySpool
from proxy_pipeline.safety import KillSwitch, RunGate
from proxy_pipeline.sources.catalog import SourceCatalog
from proxy_pipeline.telemetry.events import EventBus
from proxy_pipeline.telemetry.metrics import Metrics


@dataclass
class ControlPlane:
    """Wires Stage-0/1 control-plane components. Scanners never live here."""

    catalog: SourceCatalog
    modes: ModeRegistry
    decisions: DecisionService
    writer: DBWriter | None = None
    payloads: PayloadStore | None = None
    events: EventBus = field(default_factory=EventBus)
    metrics: Metrics = field(default_factory=Metrics)
    feedback: FeedbackStore = field(default_factory=FeedbackStore)
    kill_switch: KillSwitch = field(default_factory=KillSwitch)
    segments: SegmentQueue = field(default_factory=SegmentQueue)
    strategy_version: str = "s1"
    var_root: Path = Path("var")

    def __post_init__(self) -> None:
        self.gate = RunGate(self.kill_switch)
        self.manifests = ManifestBuilder()
        self.context = ContextBuilder(self.strategy_version, self.modes.active or "unselected")
        self.var_root.mkdir(parents=True, exist_ok=True)
        for name in ("queue", "spool", "payloads", "archive", "cache", "logs", "db"):
            (self.var_root / name).mkdir(parents=True, exist_ok=True)
        self.l4_spool = AppendOnlySpool(self.var_root / "spool" / "l4.log")
        self.l7_spool = AppendOnlySpool(self.var_root / "spool" / "l7.log")
        self.dead_letter = AppendOnlySpool(self.var_root / "spool" / "dead-letter.log")

    def request_decision(self, context: DecisionContext, *, fresh: bool = False, technical_profile: dict | None = None):
        self.kill_switch.check()
        self.events.publish(Event("decision.requested", "candidate", context.candidate_id, {"fresh": fresh}))
        try:
            record = self.decisions.decide(context, fresh=fresh)
        except DecisionBlocked:
            self.metrics.inc("decision_blocked")
            self.events.publish(Event("route.failed", "decision", context.candidate_id, {"reason": "blocked"}))
            raise
        except ValueError:
            self.metrics.inc("decision_invalid")
            self.events.publish(Event("decision.invalid", "candidate", context.candidate_id, {}))
            raise
        if record.decision is None:
            return record, None
        if self.payloads and record.decision and not record.decision.raw_response_ref:
            ref = self.payloads.put(
                {
                    "context": context.snapshot,
                    "action": record.decision.action.value,
                    "targets": [t.cidr for t in record.decision.targets],
                }
            )
            record.decision = type(record.decision)(**{**record.decision.__dict__, "raw_response_ref": ref})
        manifest = self.manifests.build(record.decision, technical_profile or {})
        if self.writer:
            payload_ref = record.decision.raw_response_ref or ""
            if self.payloads:
                payload_ref = self.payloads.put({"manifest_id": manifest.manifest_id, "targets": [t.cidr for t in manifest.targets]})
            self.writer.write_manifest(manifest, payload_ref)
        self.events.publish(
            Event(
                "manifest.committed",
                "manifest",
                manifest.manifest_id,
                {"decision_id": manifest.decision_id},
                decision_id=manifest.decision_id,
                manifest_id=manifest.manifest_id,
            )
        )
        self.metrics.inc("manifests_committed")
        return record, manifest

    def materialize_segments(self, manifest: ExecutionManifest, queue_root: Path | None = None) -> list[Segment]:
        self.gate.check_manifest(manifest)
        root = queue_root or (self.var_root / "queue")
        items = []
        for target in manifest.targets:
            for port in target.ports or (0,):
                items.append({"cidr": target.cidr, "port": port, "protocols": list(target.protocols)})
        path = root / f"{manifest.manifest_id}.seg.zst"
        checksum = write_segment_items(path, items)
        segment = Segment(
            segment_id=manifest.manifest_id,
            manifest_id=manifest.manifest_id,
            path=path,
            item_count=len(items),
            checksum_value=checksum,
        )
        self.segments.add(segment)
        if self.writer:
            self.writer.write_segment(segment)
        return [segment]
