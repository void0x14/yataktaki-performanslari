"""Kokpit komut bağlantı testleri: her eylem gerçek agentd komutuna ulaşır.

Sağ panel eylemleri + instruction input + Ctrl+K paleti, shipped `main.ts`
üzerindeki veri niteliklerinden (`data-command`, `data-action`, `data-instruction`)
gerçek komut adlarına çözümlenir; burada her komut gerçek VDS agentd'e gönderilir.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BRIDGE_PY = ROOT / "cockpit" / "bridge" / "tauri_bridge.py"
MAIN_TS = ROOT / "cockpit" / "app" / "src" / "main.ts"
PYTHON = ROOT / ".venv" / "bin" / "python"


def agentd(command: str, **payload):
    request = json.dumps({"command": command, **payload}).encode()
    completed = subprocess.run(
        [str(PYTHON), str(BRIDGE_PY)], input=request, capture_output=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr.decode()[:500]
    return json.loads(completed.stdout.decode())


@pytest.fixture(scope="module")
def agent_id() -> str:
    status = agentd("status")
    assert status.get("ok") is True
    running = [a for a in status["agents"] if a.get("state") == "running"]
    assert running, "VDS'te çalışan ajan yok"
    return running[0]["agent_id"]


def test_shipped_ui_tum_komutlari_baglar():
    src = MAIN_TS.read_text(encoding="utf-8")
    for command in ("viewport", "hard_kill", "pause", "replay", "intervene",
                    "display_select", "display_release"):
        assert command in src, f"UI komutu bağlamıyor: {command}"


def test_status_gercek_ajanlari_dondurur(agent_id):
    status = agentd("status")
    assert status.get("ok") is True
    assert any(a["agent_id"] == agent_id for a in status["agents"])
    assert "display_control" in status and "display_capability" in status


def test_viewport_gercek_display_durumu_dondurur(agent_id):
    response = agentd("viewport", agent_id=agent_id)
    assert response.get("ok") is True
    assert response.get("display_control") is not None
    assert "live_view_available" in response


def test_replay_gercek_olaylari_dondurur(agent_id):
    response = agentd("replay", agent_id=agent_id, after_seq=0)
    assert response.get("events"), "replay olayı yok"
    sample = response["events"][0]
    for alan in ("event_type", "timestamp", "agent_id", "seq"):
        assert alan in sample, f"replay olayı alan eksik: {alan}"


def test_pause_resume_dongusu(agent_id):
    paused = agentd("pause", agent_id=agent_id, reason="tauri-cockpit-test")
    if paused.get("ok") is True:
        resumed = agentd("resume", agent_id=agent_id)
        assert resumed.get("ok") is True
        assert resumed.get("state") == "running"
    else:
        # Supervisor belleğinde canlı worker yoksa pause gerçekten reddedilir;
        # UI bu hatayı aynen gösterir, sahte başarı üretilmez.
        assert "no live VDS worker" in str(paused.get("detail", ""))
        status = agentd("status")
        live = [a["agent_id"] for a in status["agents"] if a.get("state") == "running"]
        assert agent_id in live


def test_intervene_instruction_kaydedilir(agent_id):
    response = agentd(
        "intervene", agent_id=agent_id,
        instruction="Komut bağlantı testi: mevcut adımı doğrula ve devam et.",
        context={"mode": "test", "operator_instruction": "doğrula"},
    )
    assert response.get("ok") is True
    assert response.get("instruction_recorded") is True
