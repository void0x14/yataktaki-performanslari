from fastapi.testclient import TestClient

from proxy_pipeline.api.app import create_app
from proxy_pipeline.bootstrap import build_control_plane


def test_operator_screens_and_health(tmp_path):
    plane = build_control_plane(tmp_path)
    client = TestClient(create_app(plane))
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/modes").json()["active"] == "single-agent"
    assert "Source Intelligence" in client.get("/sources").text
    assert "Kill Switch" in client.get("/safety").text
    assert "proxy_pipeline" in client.get("/metrics").text
