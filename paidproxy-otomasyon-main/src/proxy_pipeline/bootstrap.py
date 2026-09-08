from __future__ import annotations

import os
from pathlib import Path

from proxy_pipeline.agents.loader import load_routes
from proxy_pipeline.decision.service import DecisionService
from proxy_pipeline.modes.registry import ModeManifest, ModeRegistry
from proxy_pipeline.persistence.db import connect
from proxy_pipeline.persistence.payloads import PayloadStore
from proxy_pipeline.persistence.writer import DBWriter
from proxy_pipeline.pipeline import ControlPlane
from proxy_pipeline.sources.catalog import SourceCatalog
from proxy_pipeline.sources.connectors import core_catalog


def build_control_plane(root: Path | None = None) -> ControlPlane:
    root = root or Path(os.environ.get("PIPELINE_KOK") or "var")
    db = connect(root / "db" / "pipeline.sqlite3")
    catalog = SourceCatalog()
    for connector in core_catalog(enabled=False):
        catalog.register(connector)
    modes = ModeRegistry()
    for name, mode_type in [
        ("single-agent", "single_agent"),
        ("manager-subagents", "manager_subagents"),
        ("router", "router"),
        ("ensemble-judge", "ensemble_judge"),
        ("debate-consensus", "debate_consensus"),
        ("human-in-loop", "human_in_loop"),
    ]:
        modes.register(ModeManifest(name, mode_type, "1", {}))
    modes.activate("single-agent")
    return ControlPlane(
        catalog=catalog,
        modes=modes,
        decisions=DecisionService(load_routes()),
        writer=DBWriter(db),
        payloads=PayloadStore(root / "payloads"),
        var_root=root,
    )
