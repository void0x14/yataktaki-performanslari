from __future__ import annotations

from typing import Any

from proxy_pipeline.domain.models import DecisionContext


class ContextBuilder:
    """Builds provenanced decision context. Never scores or ranks targets."""

    def __init__(self, strategy_version: str, mode_version: str) -> None:
        self.strategy_version = strategy_version
        self.mode_version = mode_version

    def build(self, decision_type: str, candidate_id: str, **sections: Any) -> DecisionContext:
        snapshot = {key: value for key, value in sections.items()}
        return DecisionContext(
            decision_type,
            candidate_id,
            snapshot,
            self.strategy_version,
            self.mode_version,
        )
