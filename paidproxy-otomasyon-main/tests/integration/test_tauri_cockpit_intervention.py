"""TENCERE/BONK intervention testleri: shipped payload sözleşmesini SÜRER.

TENCERE vuruşu `intervene` komutuna şu alanlarla gitmelidir:
coordinate + current_frame + target_region + operator_instruction.
Gerçek VDS agentd'e karşı çalışır (ölü ajan yerine gerçek kayıt kullanılır).
"""
from __future__ import annotations

import json
import subprocess
import sys
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


def running_agent_with_frames() -> dict:
    status = agentd("status")
    assert status.get("ok") is True
    candidates = [a for a in status["agents"]
                  if a.get("state") == "running" and a.get("last_frame_ref")]
    assert candidates, "VDS'te kare üreten çalışan ajan yok"
    return candidates[0]


def test_tencere_payload_sozlesmesi_shipped_kodda():
    src = MAIN_TS.read_text(encoding="utf-8")
    for alan in ("coordinate", "current_frame", "target_region", "operator_instruction"):
        assert alan in src, f"TENCERE payload alanı eksik: {alan}"
    assert "tencereStrike" in src


def test_intervene_context_gercek_agente_kaydedilir():
    agent = running_agent_with_frames()
    agent_id = agent["agent_id"]
    instruction = "Buraya dikkat et; bu noktadaki hatalı adımı düzelt."
    context = {
        "mode": "tencere",
        "coordinate": {"x": 640, "y": 360},
        "current_frame": agent.get("last_frame_ref"),
        "target_region": {"x": 592, "y": 312, "width": 96, "height": 96},
        "operator_instruction": instruction,
    }
    response = agentd("intervene", agent_id=agent_id, instruction=instruction, context=context)
    assert response.get("ok") is True, response
    assert response.get("instruction_recorded") is True
    assert response.get("intervention_id")


def test_intervention_replay_akışında_gorunur():
    agent = running_agent_with_frames()
    replay = agentd("replay", agent_id=agent["agent_id"], after_seq=0)
    assert replay.get("ok", True)
    kinds = {e.get("event_type") for e in replay.get("events", [])}
    assert "operator_intervention" in kinds
