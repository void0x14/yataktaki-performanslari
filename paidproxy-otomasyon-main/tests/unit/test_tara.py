from types import SimpleNamespace

import pytest

from proxy_pipeline.safety import KillSwitch, RunGate
from proxy_pipeline.scanners.adapter import MasscanAdapter
from proxy_pipeline.scanners.runner import MasscanMissing, MasscanRunner, operator_manifest


def _runner() -> MasscanRunner:
    return MasscanRunner(MasscanAdapter(RunGate(KillSwitch())), binary="masscan")


def test_tara_dry_run_command_contains_cidr_and_ports():
    manifest = operator_manifest("8.8.8.0/24", (3128, 1080))
    cmd = _runner().command(manifest, rate=500)
    assert "8.8.8.0/24" in cmd
    assert "3128,1080" in ",".join(cmd) or "3128" in cmd
    assert "--rate" in cmd
    assert "500" in cmd


def test_tara_parses_injected_masscan_stdout(tmp_path):
    manifest = operator_manifest("1.1.1.0/24", (3128,))

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        return SimpleNamespace(returncode=0, stdout="open tcp 3128 1.1.1.1\n", stderr="")

    events = _runner().run(manifest, execute=fake_run)
    assert events[0].target_ip == "1.1.1.1"
    assert events[0].port == 3128


def test_tara_errors_when_masscan_missing(monkeypatch):
    manifest = operator_manifest("1.1.1.0/24", (3128,))
    monkeypatch.setattr("proxy_pipeline.scanners.runner.shutil.which", lambda _name: None)
    with pytest.raises(MasscanMissing):
        _runner().run(manifest)
