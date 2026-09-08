import pytest
from proxy_pipeline.safety import KillSwitch, RunGate


def test_kill_switch_stops_manifest_execution():
    switch=KillSwitch(); switch.trigger('abuse'); gate=RunGate(switch)
    with pytest.raises(RuntimeError): gate.check_manifest(type('M',(),{'targets':()})())
