import pytest

from proxy_pipeline.scanners.parser import MasscanParser


def test_masscan_parser_rejects_malformed_and_accepts_open():
    assert MasscanParser().parse_line("open tcp 3128 1.1.1.1").state == "OPEN"
    with pytest.raises(ValueError):
        MasscanParser().parse_line("garbage")
