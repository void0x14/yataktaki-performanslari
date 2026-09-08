from __future__ import annotations

import json

from typer.testing import CliRunner

from proxy_pipeline.agents.loader import load_routes
from proxy_pipeline.agents.ornek import OrnekAjan
from proxy_pipeline.cli.main import app
from proxy_pipeline.decision.service import DecisionService
from proxy_pipeline.domain.models import DecisionContext, DecisionState


def test_load_routes_empty_without_hook_or_env(monkeypatch):
    monkeypatch.delenv("PIPELINE_AJAN", raising=False)
    monkeypatch.setattr("proxy_pipeline.agents.loader.hooked", None)
    assert load_routes() == []


def test_load_routes_from_pipeline_ajan(monkeypatch):
    monkeypatch.setenv("PIPELINE_AJAN", "proxy_pipeline.agents.ornek:OrnekAjan")
    routes = load_routes()
    assert len(routes) == 1
    out = routes[0].decide(
        DecisionContext("aday", "as64500", {"cidr": "1.2.3.0/24"}, "s1", "m1")
    )
    assert out["targets"][0]["cidr"] == "1.2.3.0/24"
    assert 3128 in out["targets"][0]["ports"]


def test_ornek_ajan_commits_through_decision_service():
    service = DecisionService([OrnekAjan()])
    record = service.decide(
        DecisionContext("aday", "as64500", {"cidr": "8.8.8.0/24", "ports": [3128]}, "s1", "m1")
    )
    assert record.state is DecisionState.COMMITTED
    assert record.decision.targets[0].cidr == "8.8.8.0/24"


def test_kesfet_blocked_without_agent(monkeypatch, tmp_path):
    monkeypatch.delenv("PIPELINE_AJAN", raising=False)
    monkeypatch.setattr("proxy_pipeline.agents.loader.hooked", None)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["kesfet", "as64500"])
    assert result.exit_code == 2
    assert "AJAN YOK" in result.stdout


def test_kesfet_with_ornek_ajan(monkeypatch, tmp_path):
    monkeypatch.setenv("PIPELINE_AJAN", "proxy_pipeline.agents.ornek:OrnekAjan")
    monkeypatch.chdir(tmp_path)
    kanit = json.dumps({"asn": 64500, "cidr": "1.2.3.0/24", "ports": [3128, 8080]})
    result = CliRunner().invoke(app, ["kesfet", "as64500", "--kanit", kanit])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["karar"] == "sample"
    assert payload["hedefler"][0]["cidr"] == "1.2.3.0/24"
    assert payload["hedefler"][0]["ports"] == [3128, 8080]


def test_help_lists_short_commands():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    text = result.stdout
    assert "kur" in text
    assert "kesfet" in text
    assert "tara" in text
    assert "panel" in text


def test_kur_defaults_to_var_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["kur"])
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "var" / "db" / "pipeline.sqlite3").exists()
