from __future__ import annotations

import ipaddress
import socket
import struct


def ip_to_binary(value: str) -> bytes:
    """Canonical 16-byte IP encoding. IPv4 is stored as IPv4-mapped IPv6."""
    addr = ipaddress.ip_address(value)
    if addr.version == 6:
        return addr.packed
    return ipaddress.IPv6Address(f"::ffff:{addr}").packed


def binary_to_ip(value: bytes) -> str:
    if len(value) != 16:
        raise ValueError("IP binary must be 16 bytes")
    addr = ipaddress.IPv6Address(value)
    if addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    return str(addr)


def cidr_to_binary(value: str) -> tuple[bytes, int, int]:
    network = ipaddress.ip_network(value, strict=False)
    packed = network.network_address.packed
    if network.version == 4:
        packed = ipaddress.IPv6Address(f"::ffff:{network.network_address}").packed
    return packed, int(network.prefixlen), int(network.version)


def ip_in_cidr(ip: str, cidr: str) -> bool:
    return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)


def pack_port(port: int) -> bytes:
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return struct.pack("!H", port)


def host_port(host: str, port: int) -> tuple[str, int]:
    socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host.split("%", 1)[0])
    if not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return host, port
