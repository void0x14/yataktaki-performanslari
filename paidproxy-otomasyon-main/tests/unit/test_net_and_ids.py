from proxy_pipeline.domain.net import binary_to_ip, cidr_to_binary, ip_in_cidr, ip_to_binary


def test_canonical_16_byte_ip_roundtrip():
    packed = ip_to_binary("198.51.100.10")
    assert len(packed) == 16
    assert binary_to_ip(packed) == "198.51.100.10"


def test_ipv6_roundtrip():
    packed = ip_to_binary("2001:db8::1")
    assert binary_to_ip(packed) == "2001:db8::1"


def test_cidr_binary_and_membership():
    packed, length, version = cidr_to_binary("198.51.100.0/24")
    assert length == 24
    assert version == 4
    assert len(packed) == 16
    assert ip_in_cidr("198.51.100.10", "198.51.100.0/24")
    assert not ip_in_cidr("203.0.113.1", "198.51.100.0/24")
