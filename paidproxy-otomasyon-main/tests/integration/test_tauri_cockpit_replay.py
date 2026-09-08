"""Kokpit replay/evidence entegrasyon testleri (GERÇEK VDS kayıtları).

Thumbnail ve marker modeli, hover/click/scrub/prev/next/canlıya dön geçişleri,
kronolojik event türleri ve seçime bağlı inspector alanları gerçek kayıttan beslenir.
Shipped `main.ts` bu akışı sürer; burada gerçek replay verisi doğrulanır.
"""
from __future__ import annotations

import json
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
        [str(PYTHON), str(BRIDGE_PY)], input=request, capture_output=True, timeout=90,
    )
    assert completed.returncode == 0, completed.stderr.decode()[:500]
    return json.loads(completed.stdout.decode())


@pytest.fixture(scope="module")
def replay() -> dict:
    status = agentd("status")
    assert status.get("ok") is True
    agent = next(a for a in status["agents"] if a.get("state") == "running" and a.get("last_frame_ref"))
    response = agentd("replay", agent_id=agent["agent_id"], after_seq=0)
    assert response.get("events")
    response["agent_id"] = agent["agent_id"]
    return response


def test_shipped_ui_replay_akisini_surer():
    src = MAIN_TS.read_text(encoding="utf-8")
    for fragment in ("renderFrames", "frame-strip", "data-frame", "data-event",
                     "fetch_frame", "inspect(", "scrub.oninput"):
        assert fragment in src, f"replay parçası eksik: {fragment}"


def test_frame_eventleri_thumbnail_modelini_besler(replay):
    frames = [e for e in replay["events"] if e.get("frame_ref")]
    assert len(frames) >= 1
    sample = frames[-1]
    assert sample["frame_ref"].startswith(f"agent://{replay['agent_id']}/frames/")
    assert sample.get("seq") is not None and sample.get("timestamp")


def test_event_turleri_kronolojik_ve_gecerli(replay):
    events = replay["events"]
    seqs = [e["seq"] for e in events if e.get("seq") is not None]
    assert seqs == sorted(seqs), "replay kronolojik değil"
    kinds = {e.get("event_type") for e in events}
    assert len(kinds) >= 2, f"tek tip olay akışı: {kinds}"


def test_error_marker_kaynagi_gercek(replay):
    errors = [e for e in replay["events"]
              if "error" in str(e.get("event_type", "")) or "unavailable" in str(e.get("event_type", ""))]
    assert errors, "marker testi için hata olayı yok"


def test_inspector_alanlari_gercek_kayittan_dolar(replay):
    sample = next(e for e in replay["events"] if e.get("frame_ref"))
    for alan in ("timestamp", "event_type", "agent_id", "frame_ref"):
        assert sample.get(alan), f"inspector alanı boş: {alan}"


def test_frame_artifact_gercekten_indirilebilir(replay):
    import sys
    sys.path.insert(0, str(ROOT))
    from cockpit.bridge.artifacts import ArtifactCache
    from cockpit.bridge.vds import VDSConfig
    sample = next(e for e in replay["events"] if e.get("frame_ref"))
    path = ArtifactCache(VDSConfig()).fetch(sample["frame_ref"], replay["agent_id"])
    assert path.is_file() and path.stat().st_size > 1_000
