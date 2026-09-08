from __future__ import annotations

import json
from typing import Iterable

from proxy_pipeline.domain.events import Event
from proxy_pipeline.domain.net import cidr_to_binary, ip_to_binary
from proxy_pipeline.domain.time import utc_epoch_ms


class DBWriter:
    """The only component allowed to mutate the control-plane SQLite connection."""

    def __init__(self, connection) -> None:
        self.db = connection

    def write_events(self, events: Iterable[Event]) -> int:
        rows = [
            (
                e.event_id,
                e.event_type,
                e.entity_type,
                e.entity_id,
                e.payload.get("from_state") if isinstance(e.payload, dict) else None,
                e.payload.get("to_state") if isinstance(e.payload, dict) else None,
                e.payload.get("reason") if isinstance(e.payload, dict) else None,
                e.decision_id or None,
                e.manifest_id or None,
                e.correlation_id,
                e.causation_id,
                e.producer,
                e.to_json(),
                e.occurred_at,
            )
            for e in events
        ]
        if not rows:
            return 0
        with self.db:
            self.db.executemany(
                """INSERT OR IGNORE INTO state_events(
                    event_id,event_type,entity_type,entity_id,from_state,to_state,reason,
                    decision_id,manifest_id,correlation_id,causation_id,actor,payload,occurred_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        return len(rows)

    def write_decision(self, context, record, payload_ref: str | None = None) -> None:
        decision = record.decision
        now = utc_epoch_ms()
        with self.db:
            self.db.execute(
                """INSERT OR REPLACE INTO agent_decisions(
                    decision_id,state,decision_type,candidate_id,context_hash,
                    parsed_action,mode_version,strategy_version,raw_response_ref,
                    prompt_payload_ref,prompt_hash,raw_response_hash,confidence,
                    provider,model,parent_decision_id,schema_result,
                    created_at,committed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    decision.decision_id if decision else context.correlation_id,
                    record.state.value,
                    context.decision_type,
                    context.candidate_id,
                    context.context_hash,
                    decision.action.value if decision else None,
                    context.mode_version,
                    context.strategy_version,
                    payload_ref or (decision.raw_response_ref if decision else None),
                    decision.prompt_payload_ref if decision else None,
                    decision.prompt_hash if decision else None,
                    decision.raw_response_hash if decision else None,
                    decision.confidence if decision else None,
                    decision.provider if decision else None,
                    decision.model if decision else None,
                    decision.parent_decision_id if decision else None,
                    getattr(record, "schema_result", None),
                    now,
                    now if decision and record.state.value == "COMMITTED" else None,
                ),
            )
            if decision and decision.items:
                self.db.execute("DELETE FROM decision_items WHERE decision_id=?", (decision.decision_id,))
                self.db.executemany(
                    """INSERT INTO decision_items(
                        decision_id,candidate_id,target,action,order_index,
                        resource_allocation,stop_expression,reassessment_expression,status
                    ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    [
                        (
                            decision.decision_id,
                            item.candidate_id,
                            json.dumps([t.cidr for t in item.targets]),
                            item.action.value,
                            item.order_index,
                            json.dumps(item.resource_allocation, sort_keys=True),
                            json.dumps(item.stop_expression, sort_keys=True),
                            json.dumps(item.reassessment_expression, sort_keys=True) if item.reassessment_expression else None,
                            item.status,
                        )
                        for item in decision.items
                    ],
                )

    def write_manifest(self, manifest, payload_ref: str) -> None:
        now = utc_epoch_ms()
        with self.db:
            self.db.execute(
                """INSERT OR REPLACE INTO execution_manifests(
                    manifest_id,decision_id,payload_ref,
                    target_intent,technical_profile,status,created_at
                ) VALUES (?,?,?,?,?,?,?)""",
                (
                    manifest.manifest_id,
                    manifest.decision_id,
                    payload_ref,
                    json.dumps(
                        [{"cidr": t.cidr, "ports": list(t.ports), "protocols": list(t.protocols)} for t in manifest.targets],
                        sort_keys=True,
                    ),
                    json.dumps(manifest.technical_profile, sort_keys=True),
                    manifest.status,
                    now,
                ),
            )

    def write_segment(self, segment) -> None:
        now = utc_epoch_ms()
        with self.db:
            self.db.execute(
                """INSERT OR REPLACE INTO scan_segments(
                    segment_id,manifest_id,path,checksum,item_count,cursor,lease_owner,lease_until,
                    retry_count,state,created_at,completed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    segment.segment_id,
                    segment.manifest_id,
                    str(segment.path),
                    segment.checksum,
                    getattr(segment, "item_count", 0),
                    segment.cursor,
                    segment.lease_owner,
                    segment.lease_until,
                    getattr(segment, "retry_count", 0),
                    segment.state,
                    now,
                    None,
                ),
            )

    def upsert_endpoint(self, ip: str, port: int, state: str, protocol_summary: str = "") -> int:
        now = utc_epoch_ms()
        packed = ip_to_binary(ip)
        with self.db:
            self.db.execute(
                """INSERT INTO endpoints(ip_binary,port,current_state,first_seen,last_seen,protocol_summary)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(ip_binary,port) DO UPDATE SET current_state=excluded.current_state, last_seen=excluded.last_seen""",
                (packed, port, state, now, now, protocol_summary),
            )
            row = self.db.execute("SELECT id FROM endpoints WHERE ip_binary=? AND port=?", (packed, port)).fetchone()
        return int(row["id"])

    def write_validation(self, endpoint_id: int, validation, *, manifest_id: str = "", decision_id: str = "", run_id: str = "") -> None:
        now = utc_epoch_ms()
        with self.db:
            self.db.execute(
                """INSERT INTO validations(
                    endpoint_id,protocol,result,reason,latency_ms,echo_ref,attempt,manifest_id,decision_id,run_id,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    endpoint_id,
                    validation.protocol,
                    validation.result.value if hasattr(validation.result, "value") else str(validation.result),
                    validation.reason,
                    validation.latency_ms,
                    validation.echo_ref,
                    getattr(validation, "attempt", 1),
                    manifest_id or None,
                    decision_id or None,
                    run_id or None,
                    now,
                ),
            )

    def write_outcome(self, decision_id: str, outcome: dict) -> None:
        now = utc_epoch_ms()
        with self.db:
            self.db.execute(
                """INSERT INTO decision_outcomes(
                    decision_id,item_id,outcome,cost,duration_ms,regret,evaluator,user_feedback,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    decision_id,
                    outcome.get("item_id"),
                    json.dumps(outcome, sort_keys=True),
                    outcome.get("cost"),
                    outcome.get("duration_ms"),
                    outcome.get("regret"),
                    outcome.get("evaluator"),
                    outcome.get("user_feedback"),
                    now,
                ),
            )

    def write_prefix(self, prefix: str, origin_asn: int | None, advertised_state: str = "unknown") -> int:
        packed, length, version = cidr_to_binary(prefix)
        now = utc_epoch_ms()
        with self.db:
            existing = self.db.execute(
                "SELECT id FROM prefixes WHERE network=? AND prefix_length=?",
                (packed, length),
            ).fetchone()
            if existing:
                self.db.execute(
                    "UPDATE prefixes SET last_seen=?, origin_asn=COALESCE(?,origin_asn) WHERE id=?",
                    (now, origin_asn, existing["id"]),
                )
                return int(existing["id"])
            cur = self.db.execute(
                """INSERT INTO prefixes(network,prefix_length,ip_version,origin_asn,advertised_state,first_seen,last_seen)
                   VALUES (?,?,?,?,?,?,?)""",
                (packed, length, version, origin_asn, advertised_state, now, now),
            )
            return int(cur.lastrowid)
