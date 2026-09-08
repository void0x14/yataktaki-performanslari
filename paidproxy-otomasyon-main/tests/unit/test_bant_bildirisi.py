def test_aralikli_bildiri_komutu_aralik_yazar():
    from proxy_pipeline.scanners.runner import operator_manifest
    from proxy_pipeline.scanners.adapter import MasscanAdapter
    from proxy_pipeline.safety import RunGate
    m = operator_manifest("198.51.100.0/28", (), port_dizgesi="30000-30999")
    cmd = MasscanAdapter(RunGate()).command_for(m)
    assert "30000-30999" in ",".join(cmd)

def test_aralikli_cozumleme_sinirda_kabul_reddeder():
    from proxy_pipeline.scanners.runner import operator_manifest
    from proxy_pipeline.scanners.adapter import MasscanAdapter
    from proxy_pipeline.safety import RunGate
    import pytest
    m = operator_manifest("198.51.100.0/28", (), port_dizgesi="30000-30999")
    a = MasscanAdapter(RunGate())
    ok = a.parse_stdout(m, ["open tcp 30500 198.51.100.7"])
    assert ok[0].port == 30500
    with pytest.raises(ValueError):
        a.parse_stdout(m, ["open tcp 3128 198.51.100.7"])
