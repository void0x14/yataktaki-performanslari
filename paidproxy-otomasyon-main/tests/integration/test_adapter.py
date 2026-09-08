import pytest
from proxy_pipeline.domain.models import Target, ExecutionManifest
from proxy_pipeline.safety import KillSwitch, RunGate
from proxy_pipeline.scanners.adapter import MasscanAdapter


def test_adapter_requires_manifest_port():
    gate=RunGate(KillSwitch())
    manifest=ExecutionManifest('m','d',(Target('1.1.1.0/24',(3128,)),),{})
    assert MasscanAdapter(gate).parse_stdout(manifest,['open tcp 3128 1.1.1.1'])[0].port == 3128
    with pytest.raises(ValueError): MasscanAdapter(gate).parse_stdout(manifest,['open tcp 1080 1.1.1.1'])
