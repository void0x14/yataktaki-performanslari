from __future__ import annotations

import json
from uuid import uuid4

from proxy_pipeline.domain.models import Decision, DecisionState, ExecutionManifest


class ManifestBuilder:
    """Converts a committed AI decision into an immutable execution plan."""


    def build(self, decision: Decision, technical_profile: dict, *, decision_state: str | None = None) -> ExecutionManifest:
        if not decision.decision_id:
            raise ValueError("manifest requires an AI decision id")
        if decision_state and decision_state not in {DecisionState.COMMITTED.value, None}:
            raise ValueError("only committed decisions become manifests")
        targets = decision.targets
        protocol_intent = tuple(sorted({protocol for target in targets for protocol in target.protocols}))
        return ExecutionManifest(
            manifest_id=str(uuid4()),
            decision_id=decision.decision_id,
            targets=targets,
            technical_profile=json.loads(json.dumps(technical_profile, sort_keys=True)),
            protocol_intent=protocol_intent,
            segment_plan={"item_count": sum(max(len(t.ports), 1) for t in targets)},
            status="committed",
        )
